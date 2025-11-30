import logging
import json
import time
import secrets
from aiohttp import web
from . import config

logger = logging.getLogger(__name__)


@web.middleware
async def trace_middleware(request, handler):
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

    logger.info(f"Trace: {request.method} {request.path} (Body: {len(body_bytes) if body_bytes else 0} bytes)")

    # Process request
    response = await handler(request)

    return response


async def handle_root(request):
    return web.Response(text="Supernote Private Cloud Server")


async def handle_query_server(request):
    # Endpoint: GET /api/file/query/server
    # Purpose: Device checks if the server is a valid Supernote Private Cloud instance.
    return web.json_response({"success": True})


async def handle_equipment_unlink(request):
    # Endpoint: POST /api/terminal/equipment/unlink
    # Purpose: Device requests to unlink itself from the account/server.
    # Since this is a private cloud, we can just acknowledge success.
    return web.json_response({"success": True})


async def handle_check_user_exists(request):
    # Endpoint: POST /api/official/user/check/exists/server
    # Purpose: Check if the user exists on this server.
    # For now, we'll assume any user exists to allow login to proceed.
    return web.json_response({"success": True})


async def handle_query_token(request):
    # Endpoint: POST /api/user/query/token
    # Purpose: Initial token check (often empty request)
    return web.json_response({"success": True})


async def handle_random_code(request):
    # Endpoint: POST /api/official/user/query/random/code
    # Purpose: Get challenge for password hashing
    random_code = secrets.token_hex(4)  # 8 chars
    timestamp = str(int(time.time() * 1000))
    
    return web.json_response({
        "success": True,
        "randomCode": random_code,
        "timestamp": timestamp
    })


async def handle_login(request):
    # Endpoint: POST /api/official/user/account/login/new
    # Purpose: Login with hashed password
    
    # Generate a dummy JWT-like token
    # In a real implementation, we would validate the password hash here
    token = f"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"
    
    return web.json_response({
        "success": True,
        "token": token,
        "userName": "Supernote User",
        "isBind": "Y",
        "isBindEquipment": "Y",
        "soldOutCount": 0
    })


async def handle_bind_equipment(request):
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    # We can just acknowledge success.
    return web.json_response({"success": True})


async def handle_csrf(request):
    # Endpoint: GET /api/csrf
    token = secrets.token_urlsafe(16)
    resp = web.Response(text="CSRF Token")
    resp.headers["X-XSRF-TOKEN"] = token
    return resp


def create_app():
    app = web.Application(middlewares=[trace_middleware])
    app.router.add_get("/", handle_root)
    app.router.add_get("/api/file/query/server", handle_query_server)
    app.router.add_get("/api/csrf", handle_csrf)
    app.router.add_post("/api/terminal/equipment/unlink", handle_equipment_unlink)
    app.router.add_post("/api/official/user/check/exists/server", handle_check_user_exists)
    app.router.add_post("/api/user/query/token", handle_query_token)
    app.router.add_post("/api/official/user/query/random/code", handle_random_code)
    app.router.add_post("/api/official/user/account/login/new", handle_login)
    app.router.add_post("/api/official/user/account/login/equipment", handle_login)
    app.router.add_post("/api/terminal/user/bindEquipment", handle_bind_equipment)
    
    # Add a catch-all route to log everything
    app.router.add_route("*", "/{tail:.*}", handle_root)
    return app


def run(args):
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host=config.HOST, port=config.PORT)
