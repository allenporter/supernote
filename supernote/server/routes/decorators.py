"""Decorators for route handlers."""

import functools
from collections.abc import Awaitable, Callable

from aiohttp import web

__all__ = ["authenticated_route", "public_route"]


def public_route(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as public (no authentication required)."""
    setattr(handler, "is_public", True)
    return handler


def authenticated_route(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as requiring authentication."""

    @functools.wraps(handler)
    async def wrapper(request: web.Request) -> web.StreamResponse:
        user = request.get("user")
        if not isinstance(user, str) or not user.strip():
            raise web.HTTPUnauthorized(reason="Authentication required")
        return await handler(request)

    setattr(wrapper, "is_public", False)
    return wrapper
