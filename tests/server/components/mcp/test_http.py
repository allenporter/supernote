"""Unit tests for `supernote.server.components.mcp.http`."""

from __future__ import annotations

import pytest
from aiohttp import web

from supernote.server.components.http import HttpRegistrar
from supernote.server.components.mcp.http import async_setup_http
from supernote.server.config import ServerConfig
from supernote.server.core import ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@pytest.fixture
def mcp_http_core(
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


async def test_mcp_http_platform_registers_asgi_resource_and_prefixes(
    mcp_http_core: ServerCore,
) -> None:
    registrar = HttpRegistrar()
    await async_setup_http(mcp_http_core, registrar)

    assert len(registrar.public_resources) == 1
    assert "/.well-known/oauth-authorization-server" in registrar.known_resource_paths
    assert registrar.public_prefixes == (
        "/login-bridge",
        "/authorize",
        "/token",
        "/.well-known/",
    )
