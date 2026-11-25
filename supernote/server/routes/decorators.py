"""Route handler decorators for authentication and authorization in `supernote.server`.

Provides:
- `@public_route`: marks an `aiohttp` route handler with `is_public = True` so
  `supernote.server.components.http.jwt_auth_middleware` allows unauthenticated
  requests (login challenges, health checks, Prometheus metrics, and HMAC-signed
  `/api/oss/*` transfers).
- `@interactive_session_only`: rejects static API keys and OAuth tokens.
- `@require_admin`: enforces an authenticated interactive admin session.
"""

from collections.abc import Awaitable, Callable
from functools import wraps

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.server.keys import REQUEST_USER_KEY, USER_SERVICE_KEY
from supernote.server.services.user import UserService


def public_route(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as public (no authentication required)."""
    setattr(handler, "is_public", True)
    return handler


def interactive_session_only(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as requiring an interactive login session (denying static API keys and OAuth tokens)."""
    setattr(handler, "interactive_session_only", True)
    return handler


def require_admin(
    handler: Callable[[web.Request], Awaitable[web.Response]],
) -> Callable[[web.Request], Awaitable[web.Response]]:
    """Decorator to require admin privileges over an interactive session."""

    @wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        user_service: UserService = request.app[USER_SERVICE_KEY]
        username = request.get(REQUEST_USER_KEY)
        if not username:
            return web.json_response(
                create_error_response("Unauthorized").to_dict(), status=401
            )

        user = await user_service.get_user_by_email(str(username))
        if not user or not user.is_admin:
            return web.json_response(
                create_error_response("Forbidden: Admin access required").to_dict(),
                status=403,
            )

        return await handler(request)

    interactive_session_only(wrapper)
    return wrapper
