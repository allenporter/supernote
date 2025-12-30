import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from .config import ServerConfig
from .models.base import create_error_response
from .routes import auth, file, system
from .services.file import FileService
from .services.state import StateService
from .services.storage import StorageService
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
        trace_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trace_log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            f.flush()
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
    user = user_service.verify_token(token)
    if not user:
        return web.json_response(
            create_error_response("Invalid token").to_dict(), status=401
        )

    request["user"] = user
    return await handler(request)


def create_app(
    config: ServerConfig | None = None,
    state_service: StateService | None = None,
) -> web.Application:
    if config is None:
        config = ServerConfig.load()

    app = web.Application(middlewares=[trace_middleware, jwt_auth_middleware])
    app["config"] = config

    # Initialize services
    storage_root = Path(config.storage_dir)
    storage_service = StorageService(storage_root)
    if state_service is None:
        state_service = StateService(storage_service.system_dir / "state.json")

    app["storage_service"] = storage_service
    app["state_service"] = state_service
    app["user_service"] = UserService(config.auth, state_service)
    app["file_service"] = FileService(storage_service)
    app["sync_locks"] = {}  # user -> (equipment_no, expiry_time)

    # Resolve trace log path if not set
    if not config.trace_log_file:
        config.trace_log_file = str(storage_service.system_dir / "trace.log")

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(auth.routes)
    app.add_routes(file.routes)

    # Add a catch-all route to log everything (must be last)
    app.router.add_route("*", "/{tail:.*}", system.handle_root)
    return app


def run(args: Any) -> None:
    logging.basicConfig(level=logging.DEBUG)
    config_dir = getattr(args, "config_dir", None)
    config = ServerConfig.load(config_dir)
    app = create_app(config)
    web.run_app(app, host=config.host, port=config.port)
