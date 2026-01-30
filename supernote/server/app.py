import asyncio
import importlib.resources
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp_remotes
from aiohttp import web
from aiohttp_asgi import ASGIResource
from sqlalchemy import select
from yarl import URL

from supernote.models.base import create_error_response
from supernote.server.db.migrations import run_migrations
from supernote.server.mcp.auth import create_auth_app
from supernote.server.mcp.server import create_mcp_server, run_server, set_services

from .config import ServerConfig
from .constants import MAX_UPLOAD_SIZE
from .db.models.user import UserDO
from .db.session import DatabaseSessionManager
from .events import LocalEventBus
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
from .services.coordination import SqliteCoordinationService
from .services.file import FileService
from .services.gemini import GeminiService
from .services.processor import ProcessorService
from .services.processor_modules.gemini_embedding import GeminiEmbeddingModule
from .services.processor_modules.gemini_ocr import GeminiOcrModule
from .services.processor_modules.page_hashing import PageHashingModule
from .services.processor_modules.png_conversion import PngConversionModule
from .services.processor_modules.summary import SummaryModule
from .services.schedule import ScheduleService
from .services.search import SearchService
from .services.summary import SummaryService
from .services.user import UserService
from .utils.hashing import get_md5_hash
from .utils.rate_limit import RateLimiter
from .utils.url_signer import UrlSigner

logger = logging.getLogger(__name__)

TRUNCATE_BODY_LOG = 10 * 1024


async def _write_trace_log(config: ServerConfig, log_entry: dict[str, Any]) -> None:
    """Helper to write log entry to trace file."""
    if not config.trace_log_file:
        return

    trace_log_path = Path(config.trace_log_file)

    def write_op() -> None:
        try:
            trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_log_path, "a") as f:
                f.write(json.dumps(log_entry, indent=2) + "\n")
                f.flush()
        except Exception as e:
            logger.error(f"Failed to write to trace log: {e}")

    await asyncio.to_thread(write_op)


@web.middleware
async def trace_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    # Process Request
    try:
        response = await handler(request)

        # Capture Request Body (SAFELY AFTER HANDLER)
        req_body_str = None
        if "/api/oss/upload" in request.path:
            req_body_str = "<multipart upload skipped>"
        elif request.can_read_body and not request.content_type.startswith(
            "multipart/"
        ):
            try:
                # aiohttp allows reading multiple times once buffered
                body_bytes = await request.read()
                req_body_str = body_bytes.decode("utf-8", errors="replace")
                if len(req_body_str) > TRUNCATE_BODY_LOG:
                    req_body_str = req_body_str[:2048] + "... (truncated)"
            except Exception:
                req_body_str = "<error reading body>"

        # Capture Response Body
        res_body_str = None
        if isinstance(response, web.Response) and response.body:
            if is_binary_content_type(response.content_type):
                res_body_str = "<binary data>"
            else:
                try:
                    if isinstance(response.body, bytes):
                        res_body_str = response.body.decode("utf-8", errors="replace")
                        if len(res_body_str) > TRUNCATE_BODY_LOG:
                            res_body_str = res_body_str[:2048] + "... (truncated)"
                except Exception:
                    res_body_str = "<error reading response>"

        # Write Log
        log_entry = {
            "timestamp": time.time(),
            "request": {
                "method": request.method,
                "url": str(_redact_url(request.url)),
                "headers": _sanitize_headers(dict(request.headers)),
                "body": try_parse_json(req_body_str),
            },
            "response": {
                "status": response.status,
                "headers": _sanitize_headers(dict(response.headers)),
                "body": try_parse_json(res_body_str),
            },
        }
        await _write_trace_log(request.app["config"], log_entry)
        return response

    except Exception as e:
        logger.exception(f"Error handling request: {e}")
        # Try to capture body even on error
        req_body_str = "<unknown>"
        try:
            if request.can_read_body:
                body_bytes = await request.read()
                req_body_str = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass

        log_entry = {
            "timestamp": time.time(),
            "request": {
                "method": request.method,
                "url": str(_redact_url(request.url)),
                "headers": _sanitize_headers(dict(request.headers)),
                "body": try_parse_json(req_body_str),
            },
            "error": str(e),
            "status": 500,
        }
        await _write_trace_log(request.app["config"], log_entry)
        raise


def try_parse_json(body: str | None) -> Any:
    """Attempt to parse string as JSON, return original if fails or is not string."""
    if not isinstance(body, str):
        return body
    try:
        return json.loads(body)
    except Exception:
        return body


def is_binary_content_type(content_type: str) -> bool:
    """Check if content type is likely binary."""
    binary_types = [
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "image/",
        "audio/",
        "video/",
    ]
    return any(t in content_type for t in binary_types)


def _sanitize_headers(headers: dict[str, Any]) -> dict[str, Any]:
    new_headers = headers.copy()
    if "x-access-token" in new_headers:
        new_headers["x-access-token"] = "***"
    if "Authorization" in new_headers:
        new_headers["Authorization"] = "***"
    return new_headers


def _redact_url(url: Any) -> str:
    """Redact sensitive query parameters from URL."""
    # Handle yarl.URL or string
    url_str = str(url)
    if "signature=" not in url_str and "token=" not in url_str:
        return url_str

    try:
        u = URL(url_str)
        query = u.query.copy()
        if "signature" in query:
            query["signature"] = "***"
        if "token" in query:
            query["token"] = "***"
        return str(u.with_query(query))
    except Exception:
        return url_str


@web.middleware
async def jwt_auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    # Check if the matched route handler is public
    route = request.match_info.route
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
    ):
        return await handler(request)

    # Check for x-access-token header
    if not (token := request.headers.get("x-access-token")):
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


def create_db_session_manager(db_url: str) -> DatabaseSessionManager:
    return DatabaseSessionManager(db_url)


def create_coordination_service(
    session_manager: DatabaseSessionManager,
) -> SqliteCoordinationService:
    return SqliteCoordinationService(session_manager)


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

    user_service = UserService(config.auth, coordination_service, session_manager)
    file_service = FileService(
        config.storage_root,
        blob_storage,
        user_service,
        session_manager,
        event_bus,
    )
    app["user_service"] = user_service
    app["file_service"] = file_service
    app["url_signer"] = UrlSigner(config.auth.secret_key, coordination_service)
    app["schedule_service"] = ScheduleService(session_manager)
    gemini_service = GeminiService(
        config.gemini_api_key, max_concurrency=config.gemini_max_concurrency
    )
    app["gemini_service"] = gemini_service

    summary_service = SummaryService(user_service, session_manager)
    app["summary_service"] = summary_service

    search_service = SearchService(session_manager, gemini_service, config)
    app["search_service"] = search_service

    app["sync_locks"] = {}  # user -> (equipment_no, expiry_time)
    app["rate_limiter"] = RateLimiter(coordination_service)

    processor_service = ProcessorService(
        event_bus, session_manager, file_service, summary_service
    )
    app["processor_service"] = processor_service

    # Register modules
    processor_service.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        png=PngConversionModule(file_service=file_service),
        ocr=GeminiOcrModule(
            file_service=file_service, config=config, gemini_service=gemini_service
        ),
        embedding=GeminiEmbeddingModule(
            file_service=file_service, config=config, gemini_service=gemini_service
        ),
        summary=SummaryModule(
            file_service=file_service,
            config=config,
            gemini_service=gemini_service,
            summary_service=summary_service,
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

    # Serve static frontend files
    static_path = Path(str(importlib.resources.files("supernote.server") / "static"))

    @public_route
    async def handle_index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(static_path / "index.html")

    app.router.add_get("/", handle_index)
    app.router.add_static("/static/", path=static_path, name="static")

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
        app.middlewares.append(trace_middleware)
        app.middlewares.append(jwt_auth_middleware)

        logger.info("Running database migrations...")
        await asyncio.to_thread(run_migrations, config.db_url)

        if config.ephemeral:
            await bootstrap_ephemeral_user(app)

        rs_url = f"{config.mcp_base_url}/mcp"

        logger.info(f"Mounting MCP Authorization Server at {config.base_url}")
        auth_app = create_auth_app(
            app["user_service"], app["coordination_service"], config.base_url
        )
        asgi_resource = ASGIResource(auth_app)
        app.router.register_resource(asgi_resource)

        # Inject services and start MCP server on a separate port
        set_services(
            app["search_service"], app["user_service"], app["coordination_service"]
        )
        mcp_port = config.mcp_port
        mcp_server = create_mcp_server(config.base_url, rs_url)
        mcp_task = asyncio.create_task(
            run_server(mcp_server, config.host, mcp_port, config.proxy_mode)
        )

        logger.info("Starting background services...")
        await processor_service.start()
        logger.info("Startup sequence complete.")

        app["mcp_task"] = mcp_task

    app.on_startup.append(on_startup_handler)

    async def on_shutdown_handler(app: web.Application) -> None:
        if mcp_task := app.get("mcp_task"):
            mcp_task.cancel()
            try:
                await mcp_task
            except asyncio.CancelledError:
                pass

        await processor_service.stop()
        await session_manager.close()

    app.on_shutdown.append(on_shutdown_handler)

    return app


async def bootstrap_ephemeral_user(app: web.Application) -> None:
    """Create a default user for ephemeral mode if it doesn't exist."""
    session_manager: DatabaseSessionManager = app["session_manager"]
    async with session_manager.session() as session:
        # Check if user already exists
        result = await session.execute(
            select(UserDO).where(UserDO.email == "debug@example.com")
        )
        if not result.scalar_one_or_none():
            logger.info("Creating default user debug@example.com / password")
            user = UserDO(
                email="debug@example.com",
                password_md5=get_md5_hash("password"),
                display_name="Debug User",
            )
            session.add(user)
            await session.commit()


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
