"""Shared fixtures for vertical server component unit and conformance tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx2
import pytest
from aiohttp import web
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from supernote.server.components import BUILTIN_COMPONENTS, load_component_from_spec
from supernote.server.config import ServerConfig
from supernote.server.core import ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.keys import CONFIG_KEY, USER_SERVICE_KEY
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


class LoadComponents(Protocol):
    """Callable fixture protocol for loading built-in components by domain name."""

    async def __call__(
        self,
        *domains: str,
        configs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ComponentLoader: ...


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
    app[CONFIG_KEY] = server_config
    app[USER_SERVICE_KEY] = user_service
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
async def load_components(
    component_core: ServerCore,
) -> AsyncGenerator[LoadComponents]:
    """Load built-in components by domain name (plus transitive dependencies) and stop them on teardown."""
    specs_by_domain = {spec.domain: spec for spec in BUILTIN_COMPONENTS}
    loaders: list[ComponentLoader] = []

    async def _load(
        *domains: str,
        configs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ComponentLoader:
        loader = ComponentLoader()
        pending = list(domains)
        while pending:
            domain = pending.pop(0)
            if loader.get(domain) is not None:
                continue
            if domain not in specs_by_domain:
                raise ValueError(f"Unknown built-in component domain: {domain!r}")
            component = load_component_from_spec(specs_by_domain[domain])
            loader.register(component)
            for dep in component.dependencies:
                if loader.get(dep) is None:
                    pending.append(dep)

        await loader.async_setup_all(component_core, configs or {})
        await loader.async_load_all_platforms(component_core)
        await loader.async_start_all(component_core)
        loaders.append(loader)
        return loader

    try:
        yield _load
    finally:
        for loader in reversed(loaders):
            await loader.async_stop_all(component_core)


@pytest.fixture
async def mcp_url(server_config: ServerConfig, client: Any) -> str:
    """Return the Streamable HTTP URL for the running MCP server once listening."""
    _ = client
    server_config.host = "127.0.0.1"
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        try:
            _, writer = await asyncio.open_connection(
                server_config.host, server_config.mcp_port
            )
            writer.close()
            await writer.wait_closed()
            break
        except OSError:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.02)
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
