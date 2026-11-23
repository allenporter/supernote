"""Socket.IO real-time server component."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .manager import SOCKETIO_MANAGER_KEY, SocketIOServerManager

__all__ = [
    "SOCKETIO_MANAGER_KEY",
    "SocketIOComponent",
    "SocketIOServerManager",
]


class SocketIOComponent:
    """Vertical component managing `SocketIOServerManager` and its `http` platform."""

    domain = "socketio"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    def __init__(self) -> None:
        self._manager: SocketIOServerManager | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `SocketIOServerManager` and expose it via `SOCKETIO_MANAGER_KEY`."""
        manager = SocketIOServerManager(core.config, core.user_service, core.event_bus)
        core.app[SOCKETIO_MANAGER_KEY] = manager
        self._manager = manager

    async def async_start(self, core: ServerCore) -> None:
        """No-op; Socket.IO serves directly on the primary `aiohttp` application."""

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently release the manager reference on shutdown."""
        self._manager = None
