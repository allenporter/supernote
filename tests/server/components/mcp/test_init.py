"""Unit tests for `supernote.server.components.mcp.McpComponent`."""

from __future__ import annotations

import pytest
from aiohttp import web

from supernote.server.components.mcp import McpComponent
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.keys import SEARCH_SERVICE_KEY
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.search import SearchService
from supernote.server.services.user import UserService


@pytest.fixture
def mcp_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` with `SEARCH_SERVICE_KEY` populated for `McpComponent`."""
    app = web.Application()
    app[SEARCH_SERVICE_KEY] = SearchService(session_manager, None)
    return ServerCore(
        config=server_config,
        app=app,
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


async def test_mcp_component_lifecycle(mcp_core: ServerCore) -> None:
    component = McpComponent()
    assert isinstance(component, Component)
    assert component.domain == "mcp"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(mcp_core, {})
    await loader.async_start_all(mcp_core)
    await loader.async_stop_all(mcp_core)
    await loader.async_stop_all(mcp_core)


async def test_mcp_component_stop_after_setup_only(mcp_core: ServerCore) -> None:
    loader = ComponentLoader()
    loader.register(McpComponent())

    await loader.async_setup_all(mcp_core, {})
    await loader.async_stop_all(mcp_core)
