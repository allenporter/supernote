import logging
import json
from aiohttp import web
from . import config

logger = logging.getLogger(__name__)


@web.middleware
async def trace_middleware(request, handler):
    # Read body if present
    body = None
    if request.can_read_body:
        try:
            body = await request.read()
        except Exception:
            body = b"<error reading body>"

    # Log request details
    log_entry = {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "body": body.decode("utf-8", errors="replace") if body else None,
    }

    with open(config.TRACE_LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    logger.info(f"Request: {request.method} {request.path}")

    # Process request
    response = await handler(request)

    return response


async def handle_root(request):
    return web.Response(text="Supernote Private Cloud Server")


async def handle_csrf(request):
    # Basic implementation to satisfy initial connectivity checks
    # The real implementation will likely need to generate a valid token
    return web.Response(text="CSRF Token Placeholder")


def create_app():
    app = web.Application(middlewares=[trace_middleware])
    app.router.add_get("/", handle_root)
    # Add a catch-all route to log everything
    app.router.add_route("*", "/{tail:.*}", handle_root)
    return app


def run(args):
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host=config.HOST, port=config.PORT)
