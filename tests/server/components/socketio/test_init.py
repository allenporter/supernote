"""Unit tests for `supernote.server.components.socketio`."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from supernote.server.components.socketio import (
    SOCKETIO_MANAGER_KEY,
    SocketIOComponent,
    SocketIOServerManager,
    socketio_compat_middleware,
)
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@pytest.fixture
def socketio_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures."""
    return ServerCore(
        config=server_config,
        app=web.Application(),
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


async def test_socketio_component_setup_registers_middleware_prefix_and_manager(
    socketio_core: ServerCore,
) -> None:
    component = SocketIOComponent()
    assert isinstance(component, Component)
    assert component.domain == "socketio"
    assert component.dependencies == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(socketio_core, {})
    assert socketio_core.outer_middlewares == (socketio_compat_middleware,)
    assert socketio_core.public_prefixes == ("/socket.io",)
    assert isinstance(socketio_core.app[SOCKETIO_MANAGER_KEY], SocketIOServerManager)

    await loader.async_start_all(socketio_core)
    await loader.async_stop_all(socketio_core)
    await loader.async_stop_all(socketio_core)


async def test_socketio_compat_middleware_rewrites_eio3_to_eio4() -> None:
    seen_eio: list[str | None] = []

    async def handler(request: web.Request) -> web.Response:
        seen_eio.append(request.query.get("EIO"))
        return web.Response(text="ok")

    req_eio3 = make_mocked_request("GET", "/socket.io/?EIO=3&transport=polling")
    await socketio_compat_middleware(req_eio3, handler)

    req_eio4 = make_mocked_request("GET", "/socket.io/?EIO=4&transport=polling")
    await socketio_compat_middleware(req_eio4, handler)

    req_other = make_mocked_request("GET", "/api/health?EIO=3")
    await socketio_compat_middleware(req_other, handler)

    assert seen_eio == ["4", "4", "3"]
