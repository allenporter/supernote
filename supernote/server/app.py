import logging
import json
import time
from pathlib import Path
from typing import Callable, Awaitable, Any
from aiohttp import web
from . import config
from .services.storage import StorageService
from .services.user import UserService
from .services.file import FileService
from .routes import system, auth, file

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

    try:
        with open(config.TRACE_LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            f.flush()
    except Exception as e:
        logger.error(f"Failed to write to trace log: {e}")

    logger.info(
        f"Trace: {request.method} {request.path} (Body: {len(body_bytes) if body_bytes else 0} bytes)"
    )

    # Process request
    response = await handler(request)

    return response


@web.middleware
async def jwt_auth_middleware(request, handler):
    # Only require auth for protected endpoints
    public_paths = [
        "/",
        "/api/official/user/check/exists/server",
        "/api/user/query/token",
        "/api/official/user/query/random/code",
        "/api/official/user/account/login/new",
        "/api/official/user/account/login/equipment",
        "/api/terminal/equipment/unlink",
        "/api/terminal/user/bindEquipment",
        "/api/file/query/server",
        "/api/csrf",
    ]
    if request.path in public_paths:
        return await handler(request)
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)
    token = auth_header.split(" ", 1)[1]
    from supernote.server.services.user import JWT_SECRET, JWT_ALGORITHM
    import jwt

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        request["user"] = payload["sub"]
    except jwt.InvalidTokenError:
        return web.json_response({"error": "Invalid token"}, status=401)
    return await handler(request)


def create_app() -> web.Application:
    app = web.Application(middlewares=[trace_middleware, jwt_auth_middleware])

    # Initialize services
    storage_root = Path(config.STORAGE_DIR)
    temp_root = storage_root / "temp"
    storage_service = StorageService(storage_root, temp_root)
    app["storage_service"] = storage_service
    app["user_service"] = UserService(config.USER_CONFIG_FILE)
    app["file_service"] = FileService(storage_service)

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(auth.routes)
    app.add_routes(file.routes)

    # Add a catch-all route to log everything (must be last)
    app.router.add_route("*", "/{tail:.*}", system.handle_root)
    return app


def run(args: Any) -> None:
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host=config.HOST, port=config.PORT)
