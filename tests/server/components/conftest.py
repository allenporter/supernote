"""Shared fixtures for vertical server component unit and conformance tests."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from aiohttp import web
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from supernote.server.config import ServerConfig
from supernote.server.core import ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@pytest.fixture
def component_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures for component tests."""
    app = web.Application()
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


@pytest.fixture
def mcp_url(server_config: ServerConfig, client: Any) -> str:
    """Return the Streamable HTTP URL for the running MCP server."""
    _ = client
    server_config.host = "127.0.0.1"
    return f"http://{server_config.host}:{server_config.mcp_port}/mcp"


@asynccontextmanager
async def mcp_session(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> AsyncGenerator[ClientSession]:
    """Open an initialized MCP `ClientSession` over Streamable HTTP."""
    token = auth_headers["x-access-token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as res:
            read_stream, write_stream = res[0], res[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def call_mcp_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an MCP tool over `session` and return its parsed JSON response dict."""
    result = await session.call_tool(name, arguments=arguments or {})
    assert result.content
    block = result.content[0]
    assert isinstance(block, TextContent)
    return dict(json.loads(block.text))
