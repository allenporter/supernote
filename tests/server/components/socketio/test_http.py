"""Unit tests for `supernote.server.components.socketio.http`."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from supernote.server.components.http import HttpRegistrar
from supernote.server.components.socketio import (
    SOCKETIO_MANAGER_KEY,
    SocketIOComponent,
)
from supernote.server.components.socketio.http import (
    async_setup_http,
    socketio_compat_middleware,
)
from supernote.server.config import ServerConfig
from supernote.server.core import ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@pytest.fixture
def socketio_http_core(
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


async def test_socketio_http_platform_registers_middleware_prefix_and_route(
    socketio_http_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(SocketIOComponent())
    await loader.async_setup_all(socketio_http_core, {})

    registrar = HttpRegistrar()
    await async_setup_http(socketio_http_core, registrar)

    assert registrar.outer_middlewares == (socketio_compat_middleware,)
    assert registrar.public_prefixes == ("/socket.io",)
    assert SOCKETIO_MANAGER_KEY in socketio_http_core.app
    paths = [r.canonical for r in socketio_http_core.app.router.resources()]
    assert "/socket.io/" in paths


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
