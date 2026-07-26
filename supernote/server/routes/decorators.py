"""Decorators for route handlers."""

from typing import Awaitable, Callable

from aiohttp import web


def public_route(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Decorator to mark a route handler as public (no authentication required)."""
    setattr(handler, "is_public", True)
    return handler
