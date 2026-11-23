"""Socket.IO real-time server component."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .manager import SOCKETIO_MANAGER_KEY, SocketIOServerManager

__all__ = [
    "SOCKETIO_MANAGER_KEY",
    "SocketIOComponent",
    "SocketIOServerManager",
    "socketio_compat_middleware",
]


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


class SocketIOComponent:
    """Vertical component managing Socket.IO attachment, EIO compat middleware, and auth exemption."""

    domain = "socketio"
    dependencies: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._manager: SocketIOServerManager | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Attach `SocketIOServerManager`, register EIO compat middleware, and exempt `/socket.io`."""
        core.register_middleware(socketio_compat_middleware, pre_auth=True)
        core.register_public_prefix("/socket.io")
        manager = SocketIOServerManager(core.config, core.user_service, core.event_bus)
        manager.attach_to_app(core.app)
        self._manager = manager

    async def async_start(self, core: ServerCore) -> None:
        """No-op; Socket.IO serves directly on the primary `aiohttp` application."""

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently release the manager reference on shutdown."""
        self._manager = None
