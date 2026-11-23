"""Model Context Protocol (MCP) and OAuth 2.1 Authorization Server component.

Provides an OAuth 2.1 Authorization Server (`supernote.server.components.mcp.auth`)
mounted on the primary `aiohttp` port via `ASGIResource` and a Streamable HTTP MCP
Resource Server (`supernote.server.components.mcp.server`) listening on `mcp_port`
(`8081`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore
from supernote.server.keys import SEARCH_SERVICE_KEY

__all__ = ["McpComponent"]

logger = logging.getLogger(__name__)

_MCP_OAUTH_PUBLIC_PREFIXES = (
    "/login-bridge",
    "/authorize",
    "/token",
    "/.well-known/",
)


class McpComponent:
    """Vertical component managing the OAuth 2.1 ASGI mount and FastMCP server task."""

    domain = "mcp"
    dependencies: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._mcp_server: Any | None = None
        self._task: asyncio.Task[None] | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Mount the OAuth 2.1 ASGI app and prepare the FastMCP resource server."""
        from aiohttp_asgi import ASGIResource  # noqa: PLC0415

        from .auth import create_auth_app  # noqa: PLC0415
        from .server import create_mcp_server, set_services  # noqa: PLC0415

        logger.info("Mounting MCP Authorization Server at %s", core.config.base_url)
        auth_app = create_auth_app(
            core.user_service,
            core.coordination,
            core.config.base_url,
        )
        asgi_resource = ASGIResource(auth_app)
        core.app.router.register_resource(asgi_resource)

        known_paths = (
            path
            for route in auth_app.routes
            if isinstance(path := getattr(route, "path", None), str)
        )
        core.register_public_resource(asgi_resource, known_paths=known_paths)
        for prefix in _MCP_OAUTH_PUBLIC_PREFIXES:
            core.register_public_prefix(prefix)

        set_services(
            core.app[SEARCH_SERVICE_KEY],
            core.user_service,
            core.coordination,
        )
        rs_url = f"{core.config.mcp_base_url}/mcp"
        self._mcp_server = create_mcp_server(core.config.base_url, rs_url)

    async def async_start(self, core: ServerCore) -> None:
        """Start the background Streamable HTTP MCP resource server task."""
        from .server import run_server  # noqa: PLC0415

        assert self._mcp_server is not None
        self._task = asyncio.create_task(
            run_server(
                self._mcp_server,
                core.config.host,
                core.config.mcp_port,
                core.config.proxy_mode,
            ),
            name="mcp-resource-server",
        )

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently cancel and await the background MCP server task."""
        task = self._task
        self._task = None
        self._mcp_server = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
