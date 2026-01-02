import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from supernote.models.base import create_error_response

from .config import ServerConfig
from .db.session import DatabaseSessionManager
from .routes import auth, file, schedule, system
from .services.blob import LocalBlobStorage
from .services.coordination import LocalCoordinationService
from .services.file import FileService
from .services.schedule import ScheduleService
from .services.state import StateService
from .services.user import UserService

logger = logging.getLogger(__name__)


@web.middleware
async def trace_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    # Skip reading body for upload endpoints to avoid consuming the stream
    # which breaks multipart parsing in the handler.
    if "/upload/data/" in request.path:
        return await handler(request)

    # Read body if present
    body_bytes = None
    if request.can_read_body:
        try:
            body_bytes = await request.read()
        except Exception as e:
            logger.error(f"Error reading body: {e}")
            body_bytes = b"<error reading body>"

    body_str = None
    if body_bytes:
        try:
            body_str = body_bytes.decode("utf-8", errors="replace")
            # Truncate body if it's too long (e.g. > 1KB)
            if len(body_str) > 1024:
                body_str = body_str[:1024] + "... (truncated)"
        except Exception:
            body_str = "<binary data>"

    # Log request details
    log_entry = {
        "timestamp": time.time(),
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "body": body_str,
    }

    # Get config from app
    server_config: ServerConfig = request.app["config"]
    if not server_config.trace_log_file:
        return await handler(request)

    trace_log_path = Path(server_config.trace_log_file)

    try:

        def write_trace() -> None:
            trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
                f.flush()

        await asyncio.to_thread(write_trace)
    except Exception as e:
        logger.error(f"Failed to write to trace log at {trace_log_path}: {e}")

    logger.info(
        f"Trace: {request.method} {request.path} (Body: {len(body_bytes) if body_bytes else 0} bytes)"
    )

    # Process request
    response = await handler(request)

    return response


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

    request["user"] = session.username
    request["equipment_no"] = session.equipment_no
    return await handler(request)


def create_db_session_manager(db_url: str) -> DatabaseSessionManager:
    return DatabaseSessionManager(db_url)


def create_app(
    config: ServerConfig,
    state_service: StateService | None = None,
) -> web.Application:
    app = web.Application(middlewares=[trace_middleware, jwt_auth_middleware])
    app["config"] = config

    # Initialize services
    blob_storage = LocalBlobStorage(config.storage_root)
    if state_service is None:
        state_service = StateService(config.storage_root / "system" / "state.json")

    session_manager = create_db_session_manager(config.db_url)
    coordination_service = LocalCoordinationService()

    app["session_manager"] = session_manager
    app["state_service"] = state_service
    app["coordination_service"] = coordination_service
    user_service = UserService(
        config.auth, state_service, coordination_service, session_manager
    )
    file_service = FileService(
        config.storage_root,
        blob_storage,
        user_service,
        session_manager,
    )
    app["user_service"] = user_service
    app["file_service"] = file_service
    app["schedule_service"] = ScheduleService(session_manager)
    app["sync_locks"] = {}  # user -> (equipment_no, expiry_time)

    # Resolve trace log path if not set
    if not config.trace_log_file:
        config.trace_log_file = str(config.storage_root / "system" / "trace.log")

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(auth.routes)
    app.add_routes(file.routes)
    app.add_routes(schedule.routes)

    # Add a catch-all route to log everything (must be last)
    app.router.add_route("*", "/{tail:.*}", system.handle_root)

    async def on_shutdown_handler(app: web.Application) -> None:
        await session_manager.close()

    app.on_shutdown.append(on_shutdown_handler)

    return app


def run(args: Any) -> None:
    logging.basicConfig(level=logging.DEBUG)
    config_dir = getattr(args, "config_dir", None)
    config = ServerConfig.load(config_dir)
    app = create_app(config)
    web.run_app(app, host=config.host, port=config.port)
