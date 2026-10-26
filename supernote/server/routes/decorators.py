"""Route handler decorators for authentication bypass in `supernote.server.app`.

Provides `@public_route`, which marks an `aiohttp` route handler with `is_public = True`
so `supernote.server.app.jwt_auth_middleware` allows unauthenticated requests (used by
login challenge endpoints, health checks, Prometheus metrics, and HMAC-signed `/api/oss/*`
file transfer endpoints).
"""

from collections.abc import Awaitable, Callable

from aiohttp import web


def public_route(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as public (no authentication required)."""
    setattr(handler, "is_public", True)
    return handler
