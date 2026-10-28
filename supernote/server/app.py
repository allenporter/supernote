import asyncio
import importlib.resources
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp_remotes
from aiohttp import web
from aiohttp.web_urldispatcher import SystemRoute
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from supernote.models.base import create_error_response
from supernote.models.user import UserRegisterDTO
from supernote.server.db.migrations import run_migrations
from supernote.server.utils.auth_utils import get_token_from_request

from .ai.models.embedding import create_embedding_model
from .ai.models.ocr import create_ocr_model
from .ai.models.summary import create_summary_model
from .config import AuthConfig, ServerConfig
from .constants import MAX_UPLOAD_SIZE
from .db.session import DatabaseSessionManager
from .events import LocalEventBus
from .metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL
from .routes import (
    admin,
    auth,
    extended,
    file_device,
    file_web,
    oss,
    schedule,
    summary,
    system,
)
from .routes.decorators import public_route
from .services.blob import LocalBlobStorage
from .services.conversion import ConversionService
from .services.coordination import CoordinationService, SqliteCoordinationService
from .services.file import FileService
from .services.integrity import IntegrityService
from .services.processor import ProcessorService
from .services.processor_modules.embedding import EmbeddingModule
from .services.processor_modules.ocr import OcrModule
from .services.processor_modules.page_hashing import PageHashingModule
from .services.processor_modules.png_conversion import PngConversionModule
from .services.processor_modules.summary import SummaryModule
from .services.processor_modules.task_extraction import TaskExtractionModule
from .services.schedule import ScheduleService
from .services.search import SearchService
from .services.summary import SummaryService
from .services.user import UserService
from .services.webhook import WebhookService
from .socket import setup_socketio
from .trace import trace_middleware
from .utils.hashing import get_md5_hash
from .utils.prompt_loader import PROMPT_LOADER
from .utils.rate_limit import RateLimiter
from .utils.url_signer import UrlSigner

logger = logging.getLogger(__name__)


@web.middleware
async def socketio_compat_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Rewrite Socket.IO requests query parameters from EIO=3 (Engine.IO v3) to EIO=4 for protocol compatibility."""
    if request.path.startswith("/socket.io/") and request.query.get("EIO") == "3":
        new_query = dict(request.query)
        new_query["EIO"] = "4"
        request = request.clone(rel_url=request.rel_url.with_query(new_query))
    return await handler(request)


@web.middleware
async def metrics_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    start_time = time.perf_counter()
    status = 500
    try:
        response = await handler(request)
        status = response.status
        return response
    except web.HTTPException as ex:
        status = ex.status
        raise
    except Exception:
        status = 500
        raise
    finally:
        duration = time.perf_counter() - start_time
        route = request.match_info.route
        resource = route.resource if route else None

        if resource:
            info = resource.get_info()
            path_pattern = info.get("formatter") or info.get("path") or request.path
            if route.name == "static" or path_pattern.startswith("/static/"):
                path_pattern = "/static/{filename}"
        else:
            path_pattern = f"HTTP {status}"

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path_pattern, status=str(status)
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method, path=path_pattern
        ).observe(duration)


@web.middleware
async def jwt_auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    # Check if the matched route handler is public
    route = request.match_info.route
    if route is None:
        return await handler(request)

    if isinstance(route, SystemRoute):
        return await handler(request)

    if route.resource and route.resource is request.app.get("mcp_asgi_resource"):
        return await handler(request)

    handler_func = getattr(route, "handler", None)
    if handler_func and getattr(handler_func, "is_public", False):
        return await handler(request)

    # Also allow public access to MCP OAuth which is registered without a
    # decorator.
    if (
        request.path.startswith("/static/")
        or request.path == "/favicon.ico"
        # Allow public access to auth routes
        or request.path.startswith("/login-bridge")
        or request.path.startswith("/authorize")
        or request.path.startswith("/token")
        or request.path.startswith("/.well-known/")
        or request.path.startswith("/socket.io")
    ):
        return await handler(request)

    if not (token := get_token_from_request(request)):
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    user_service: UserService = request.app["user_service"]
    session = await user_service.verify_token(token)
    if not session:
        return web.json_response(
            create_error_response("Invalid token").to_dict(), status=401
        )

    request["user"] = session.email
    request["equipment_no"] = session.equipment_no
    return await handler(request)


@web.middleware
async def static_cache_control_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Ensure frontend HTML and static assets revalidate across server upgrades."""
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def create_db_session_manager(db_url: str) -> DatabaseSessionManager:
    return DatabaseSessionManager(db_url)


def create_coordination_service(
    session_manager: DatabaseSessionManager,
) -> SqliteCoordinationService:
    return SqliteCoordinationService(session_manager)


def create_user_service(
    auth_config: AuthConfig,
    coordination_service: CoordinationService,
    session_manager: DatabaseSessionManager,
) -> UserService:
    return UserService(auth_config, coordination_service, session_manager)


def create_app(config: ServerConfig) -> web.Application:
    app = web.Application(client_max_size=MAX_UPLOAD_SIZE)
    app["config"] = config

    # Initialize services
    blob_storage = LocalBlobStorage(config.storage_root)

    session_manager = create_db_session_manager(config.db_url)
    coordination_service = create_coordination_service(session_manager)

    app["session_manager"] = session_manager
    app["coordination_service"] = coordination_service
    app["blob_storage"] = blob_storage
    event_bus = LocalEventBus()
    app["event_bus"] = event_bus

    user_service = create_user_service(
        config.auth, coordination_service, session_manager
    )
    file_service = FileService(
        config.storage_root,
        blob_storage,
        user_service,
        session_manager,
        event_bus,
    )
    app["user_service"] = user_service
    app["file_service"] = file_service
    app["integrity_service"] = IntegrityService(session_manager, blob_storage)
    app["schedule_service"] = ScheduleService(session_manager, event_bus)
    ocr_model = create_ocr_model(config)
    summary_model = create_summary_model(config)
    embedding_model = create_embedding_model(config)
    app["ocr_model"] = ocr_model
    app["summary_model"] = summary_model
    app["embedding_model"] = embedding_model

    if config.prompts_dir:
        PROMPT_LOADER.configure(Path(config.prompts_dir))

    summary_service = SummaryService(user_service, session_manager, event_bus)
    app["summary_service"] = summary_service

    search_service = SearchService(session_manager, embedding_model)
    app["search_service"] = search_service

    app["rate_limiter"] = RateLimiter(coordination_service)

    processor_service = ProcessorService(
        event_bus, session_manager, file_service, summary_service, coordination_service
    )
    app["processor_service"] = processor_service
    app["conversion_service"] = ConversionService(
        session_manager=session_manager,
        blob_storage=blob_storage,
        user_service=user_service,
        processor_service=processor_service,
    )

    webhook_service = WebhookService(config.webhooks, event_bus, user_service)
    app["webhook_service"] = webhook_service

    # Register modules
    png_enabled = (ocr_model is not None) or (
        config.web_enabled and config.web_notebook_preview
    )
    processor_service.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        png=PngConversionModule(file_service=file_service) if png_enabled else None,
        ocr=OcrModule(file_service=file_service, ocr_model=ocr_model),
        embedding=EmbeddingModule(
            file_service=file_service, embedding_model=embedding_model
        ),
        summary=SummaryModule(
            file_service=file_service,
            summary_service=summary_service,
            summary_model=summary_model,
        ),
        task_extraction=TaskExtractionModule(
            file_service=file_service,
            schedule_service=app["schedule_service"],
            enabled=ocr_model is not None,
        ),
    )

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(admin.routes)
    app.add_routes(auth.routes)
    app.add_routes(file_web.routes)
    app.add_routes(file_device.routes)
    app.add_routes(oss.routes)
    app.add_routes(schedule.routes)
    app.add_routes(summary.routes)
    app.add_routes(extended.routes)

    # Attach Socket.IO real-time server manager
    setup_socketio(app, config, user_service, event_bus)

    # Serve static frontend files
    if config.web_enabled:
        static_path = Path(
            str(importlib.resources.files("supernote.server") / "static")
        )

        @public_route
        async def handle_index(request: web.Request) -> web.FileResponse:
            return web.FileResponse(
                static_path / "index.html",
                headers={"Cache-Control": "no-cache"},
            )

        app.router.add_get("/", handle_index)
        app.router.add_static("/static/", path=static_path, name="static")

    if config.metrics_enabled:

        @public_route
        async def handle_metrics(request: web.Request) -> web.Response:
            data = generate_latest()
            return web.Response(
                body=data, headers={"Content-Type": CONTENT_TYPE_LATEST}
            )

        app.router.add_get(config.metrics_path, handle_metrics)
        logger.info(f"Exposing Prometheus metrics at {config.metrics_path}")

    # Register Middlewares
    async def on_startup_handler(app: web.Application) -> None:
        # Configure proxy middleware based on config
        if config.proxy_mode == "strict":
            # XForwardedStrict requires explicit trusted proxy IPs
            # Convert list of strings to list of lists for aiohttp-remotes
            trusted = [[ip] for ip in config.trusted_proxies]
            await aiohttp_remotes.setup(
                app,
                aiohttp_remotes.XForwardedStrict(trusted),
            )
        elif config.proxy_mode == "relaxed":
            # XForwardedRelaxed trusts the immediate upstream proxy
            await aiohttp_remotes.setup(app, aiohttp_remotes.XForwardedRelaxed())

        # Register trace and auth middlewares after proxy setup to avoid clone errors
        app.middlewares.append(socketio_compat_middleware)
        if config.metrics_enabled:
            app.middlewares.append(metrics_middleware)
        app.middlewares.append(trace_middleware)
        app.middlewares.append(jwt_auth_middleware)
        app.middlewares.append(static_cache_control_middleware)

        logger.info("Running database migrations...")
        await asyncio.to_thread(run_migrations, config.db_url, config=config)

        secret_key = await user_service.get_secret_key()
        app["url_signer"] = UrlSigner(secret_key, coordination_service)

        if config.ephemeral:
            await bootstrap_ephemeral_user(app)

        if config.mcp_enabled:
            from aiohttp_asgi import ASGIResource  # noqa: PLC0415

            from supernote.server.mcp.auth import create_auth_app  # noqa: PLC0415
            from supernote.server.mcp.server import (  # noqa: PLC0415
                create_mcp_server,
                run_server,
                set_services,
            )

            rs_url = f"{config.mcp_base_url}/mcp"

            logger.info(f"Mounting MCP Authorization Server at {config.base_url}")
            auth_app = create_auth_app(
                app["user_service"], app["coordination_service"], config.base_url
            )
            asgi_resource = ASGIResource(auth_app)
            app.router.register_resource(asgi_resource)
            app["mcp_asgi_resource"] = asgi_resource

            # Inject services and start MCP server on a separate port
            set_services(
                app["search_service"], app["user_service"], app["coordination_service"]
            )
            mcp_port = config.mcp_port
            mcp_server = create_mcp_server(config.base_url, rs_url)
            app["mcp_task"] = asyncio.create_task(
                run_server(mcp_server, config.host, mcp_port, config.proxy_mode)
            )

        logger.info("Starting background services...")
        await processor_service.start()
        await webhook_service.start()
        logger.info("Startup sequence complete.")

    app.on_startup.append(on_startup_handler)

    async def on_shutdown_handler(app: web.Application) -> None:
        if mcp_task := app.get("mcp_task"):
            mcp_task.cancel()
            try:
                await mcp_task
            except asyncio.CancelledError:
                pass

        await webhook_service.stop()
        await processor_service.stop()
        await session_manager.close()

    app.on_shutdown.append(on_shutdown_handler)

    return app


async def bootstrap_ephemeral_user(app: web.Application) -> None:
    """Create a default admin user and system folders for ephemeral mode if not present."""
    user_service: UserService = app["user_service"]
    if not await user_service.check_user_exists("debug@example.com"):
        logger.info("Creating default user debug@example.com / password")
        await user_service.register(
            UserRegisterDTO(
                email="debug@example.com",
                password=get_md5_hash("password"),
                user_name="Debug User",
            )
        )


def run(args: Any) -> None:
    # Robust logging setup
    FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=FORMAT, force=True)

    # Suppress noisy library logs
    logging.getLogger("aiosqlite").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.INFO)

    config_dir = getattr(args, "config_dir", None)
    config = ServerConfig.load(config_dir)
    app = create_app(config)

    # Standard access log format for aiohttp
    ACCESS_LOG_FORMAT = '%a %t "%r" %s %b "%{Referer}i" "%{User-Agent}i" (%Tf)'

    web.run_app(
        app,
        host=config.host,
        port=config.port,
        access_log=logging.getLogger("aiohttp.access"),
        access_log_format=ACCESS_LOG_FORMAT,
    )
