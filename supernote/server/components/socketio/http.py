"""HTTP platform setup for the Socket.IO component."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiohttp import web

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore

from .manager import SOCKETIO_MANAGER_KEY

__all__ = ["async_setup_http", "socketio_compat_middleware"]


@web.middleware
async def socketio_compat_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Rewrite Socket.IO query parameters from EIO=3 (Engine.IO v3) to EIO=4 for compatibility."""
    if request.path.startswith("/socket.io/") and request.query.get("EIO") == "3":
        new_query = dict(request.query)
        new_query["EIO"] = "4"
        request = request.clone(rel_url=request.rel_url.with_query(new_query))
    return await handler(request)


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register Socket.IO EIO compat middleware, `/socket.io` exemption, and routes."""
    registrar.add_middleware(socketio_compat_middleware, pre_auth=True)
    registrar.add_public_prefix("/socket.io")
    core.app[SOCKETIO_MANAGER_KEY].attach_to_app(core.app)
