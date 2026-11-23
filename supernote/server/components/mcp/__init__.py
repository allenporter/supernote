"""Model Context Protocol (MCP) and OAuth 2.1 Authorization Server component.

Provides an OAuth 2.1 Authorization Server (`supernote.server.components.mcp.http`)
mounted via the `http` platform and a Streamable HTTP MCP Resource Server
(`supernote.server.components.mcp.server`) listening on `mcp_port` (`8081`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore
from supernote.server.keys import (
    EVENT_LOG_SERVICE_KEY,
    SCHEDULE_SERVICE_KEY,
    SEARCH_SERVICE_KEY,
)

__all__ = ["McpComponent"]


class McpComponent:
    """Vertical component managing the FastMCP resource server and its `http` OAuth platform."""

    domain = "mcp"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    def __init__(self) -> None:
        self._mcp_server: Any | None = None
        self._task: asyncio.Task[None] | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Bind services and prepare the FastMCP resource server."""
        from .server import create_mcp_server, set_services  # noqa: PLC0415

        set_services(
            core.app[SEARCH_SERVICE_KEY],
            core.user_service,
            core.coordination,
            schedule_service=core.app[SCHEDULE_SERVICE_KEY],
            event_log_service=core.app[EVENT_LOG_SERVICE_KEY],
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
