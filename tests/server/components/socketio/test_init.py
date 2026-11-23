"""Unit tests for `supernote.server.components.socketio`."""

from __future__ import annotations

import pytest
from aiohttp import web

from supernote.server.components.socketio import (
    SOCKETIO_MANAGER_KEY,
    SocketIOComponent,
    SocketIOServerManager,
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


async def test_socketio_component_lifecycle(socketio_core: ServerCore) -> None:
    component = SocketIOComponent()
    assert isinstance(component, Component)
    assert component.domain == "socketio"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(socketio_core, {})
    assert isinstance(socketio_core.app[SOCKETIO_MANAGER_KEY], SocketIOServerManager)

    await loader.async_start_all(socketio_core)
    await loader.async_stop_all(socketio_core)
    await loader.async_stop_all(socketio_core)
