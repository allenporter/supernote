import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp_remotes
from aiohttp import web
from yarl import URL

from supernote.models.base import create_error_response

from .config import ServerConfig
from .constants import MAX_UPLOAD_SIZE
from .db.session import DatabaseSessionManager
from .events import LocalEventBus
from .routes import admin, auth, file_device, file_web, oss, schedule, summary, system
from .services.blob import LocalBlobStorage
from .services.coordination import SqliteCoordinationService
from .services.file import FileService
from .services.processor import ProcessorService
from .services.schedule import ScheduleService
from .services.summary import SummaryService
from .services.user import UserService
from .utils.rate_limit import RateLimiter
from .utils.url_signer import UrlSigner

logger = logging.getLogger(__name__)

TRUNCATE_BODY_LOG = 10 * 1024


@web.middleware
async def trace_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    # Skip reading body for upload endpoints to avoid consuming the stream
    # which breaks multipart parsing in the handler.
    req_body_str = None
    if "/api/oss/upload" in request.path:
        req_body_str = "<multipart upload skipped>"
    elif request.can_read_body:
        try:
            # Check content type for request
            if is_binary_content_type(request.content_type):
                req_body_str = "<binary data>"
            else:
                body_bytes = await request.read()
                req_body_str = body_bytes.decode("utf-8", errors="replace")
                # Truncate body if it's too long
                if len(req_body_str) > TRUNCATE_BODY_LOG:
                    req_body_str = req_body_str[:2048] + "... (truncated)"
        except Exception as e:
            logger.error(f"Error reading request body: {e}")
            req_body_str = "<error reading body>"

    # Process Request
    response = await handler(request)

    # Capture Response Body
    res_body_str = None
    if isinstance(response, web.Response) and response.body:
        # Check content type for response
        if is_binary_content_type(response.content_type):
            res_body_str = "<binary data>"
        else:
            try:
                # response.body is bytes/payload
                if isinstance(response.body, bytes):
                    res_body_str = response.body.decode("utf-8", errors="replace")
                    if len(res_body_str) > TRUNCATE_BODY_LOG:
                        res_body_str = res_body_str[:2048] + "... (truncated)"
                else:
                    res_body_str = "<stream/payload>"
            except Exception:
                res_body_str = "<error reading response>"

    # Write Log
    server_config: ServerConfig = request.app["config"]
    if server_config.trace_log_file:
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

        trace_log_path = Path(server_config.trace_log_file)
        try:

            def write_trace() -> None:
                trace_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(trace_log_path, "a") as f:
                    f.write(json.dumps(log_entry, indent=2) + "\n")
                    f.flush()

            await asyncio.to_thread(write_trace)
        except Exception as e:
            logger.error(f"Failed to write to trace log: {e}")

    return response


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
    summary_service = SummaryService(user_service, session_manager)
    app["summary_service"] = summary_service
    app["sync_locks"] = {}  # user -> (equipment_no, expiry_time)
    app["rate_limiter"] = RateLimiter(coordination_service)

    processor_service = ProcessorService(
        event_bus, session_manager, file_service, summary_service
    )
    app["processor_service"] = processor_service

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(admin.routes)
    app.add_routes(auth.routes)
    app.add_routes(file_web.routes)
    app.add_routes(file_device.routes)
    app.add_routes(oss.routes)
    app.add_routes(schedule.routes)
    app.add_routes(summary.routes)

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

        if config.trace_log_file:
            app.middlewares.append(trace_middleware)

        app.middlewares.append(jwt_auth_middleware)
        await session_manager.create_all_tables()
        await processor_service.start()

    app.on_startup.append(on_startup_handler)

    async def on_shutdown_handler(app: web.Application) -> None:
        await processor_service.stop()
        await session_manager.close()

    app.on_shutdown.append(on_shutdown_handler)

    return app


def run(args: Any) -> None:
    logging.basicConfig(level=logging.DEBUG)
    config_dir = getattr(args, "config_dir", None)
    config = ServerConfig.load(config_dir)
    app = create_app(config)
    web.run_app(app, host=config.host, port=config.port)
