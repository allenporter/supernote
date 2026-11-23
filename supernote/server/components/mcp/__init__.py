"""Model Context Protocol (MCP) Resource Server and platform host component.

Provides `McpComponent`, `McpRegistrar` (passed into
``<component>.mcp:async_setup_mcp(core, registrar)`` for components declaring
``platforms = ("mcp",)``), `instrument_mcp_tool`, and `get_authenticated_user_id`
for tool handlers. Depends on `oauth` (`supernote.server.components.oauth`) for
OAuth 2.1 authorization endpoints.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, ParamSpec, cast

from supernote.server.components.mcp.metrics import (
    init_mcp_metrics,
    track_mcp_tool_call,
)
from supernote.server.core import ServerCore
from supernote.server.events import bind_event_actor

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from supernote.server.components.oauth.models import SupernoteAccessToken

__all__ = [
    "McpComponent",
    "McpRegistrar",
    "get_authenticated_actor",
    "get_authenticated_user_id",
    "instrument_mcp_tool",
]

_P = ParamSpec("_P")


def _get_authenticated_token() -> SupernoteAccessToken | None:
    """Return the active `SupernoteAccessToken` from the MCP auth context, if any."""
    from mcp.server.auth.middleware.auth_context import (  # noqa: PLC0415
        auth_context_var,
    )

    if not (auth_context := auth_context_var.get()):
        return None
    return cast("SupernoteAccessToken", auth_context.access_token)


def get_authenticated_user_id() -> int | None:
    """Return the authenticated user ID from the active MCP bearer auth context."""
    token = _get_authenticated_token()
    return token.user_id if token is not None else None


def get_authenticated_actor() -> str | None:
    """Return the canonical actor identifier for the active MCP auth context."""
    token = _get_authenticated_token()
    return token.actor if token is not None else None


def instrument_mcp_tool(
    tool: str,
) -> Callable[
    [Callable[_P, Awaitable[dict[str, Any]]]],
    Callable[_P, Awaitable[dict[str, Any]]],
]:
    """Wrap an MCP tool handler to bind caller actor and record Prometheus metrics."""

    def decorator(
        fn: Callable[_P, Awaitable[dict[str, Any]]],
    ) -> Callable[_P, Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> dict[str, Any]:
            with (
                bind_event_actor(get_authenticated_actor()),
                track_mcp_tool_call(tool=tool) as call,
            ):
                result = await fn(*args, **kwargs)
                call.set_succeeded(result.get("success") is True)
                return result

        return wrapper

    return decorator


class McpRegistrar:
    """Registrar passed into ``<component>.mcp:async_setup_mcp(core, registrar)``."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}
        self._applied: set[str] = set()

    def add_tool(
        self,
        fn: Callable[..., Awaitable[dict[str, Any]]],
        *,
        name: str | None = None,
    ) -> None:
        """Register an async MCP tool handler wrapped with Prometheus metrics."""
        tool_name = (name or getattr(fn, "__name__", "")).strip()
        if not tool_name:
            raise ValueError("MCP tool name must be non-empty")
        if tool_name in self._tools:
            raise ValueError(f"MCP tool {tool_name!r} is already registered")
        self._tools[tool_name] = instrument_mcp_tool(tool_name)(fn)

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Registered platform tool names in registration order."""
        return tuple(self._tools)

    def apply_to_server(self, mcp: MCPServer) -> None:
        """Idempotently initialize metrics and mount registered tools onto ``mcp``."""
        pending = [
            (tool_name, handler)
            for tool_name, handler in self._tools.items()
            if tool_name not in self._applied
        ]
        if not pending:
            return
        init_mcp_metrics(tool_name for tool_name, _ in pending)
        for tool_name, handler in pending:
            mcp.tool(name=tool_name)(handler)
            self._applied.add(tool_name)


class McpComponent:
    """Platform host component managing the FastMCP resource server and tool registration."""

    domain = "mcp"
    dependencies: tuple[str, ...] = ("oauth",)
    platforms: tuple[str, ...] = ()
    hosted_platforms: tuple[str, ...] = ("mcp",)

    def __init__(self) -> None:
        self._mcp_server: MCPServer | None = None
        self._registrar: McpRegistrar | None = None
        self._task: asyncio.Task[None] | None = None

    def get_platform_registrar(self) -> McpRegistrar:
        """Return the `McpRegistrar` initialized during `async_setup`."""
        assert self._registrar is not None
        return self._registrar

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Initialize `McpRegistrar` and prepare the FastMCP resource server."""
        from .server import create_mcp_server  # noqa: PLC0415

        rs_url = f"{core.config.mcp_base_url}/mcp"
        self._mcp_server = create_mcp_server(
            core.config.base_url, rs_url, core.user_service
        )
        self._registrar = McpRegistrar()

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Mount all registered platform MCP tools onto the FastMCP server."""
        assert self._mcp_server is not None
        self.get_platform_registrar().apply_to_server(self._mcp_server)

    async def async_start(self, core: ServerCore) -> None:
        """Apply platform tools and start the background Streamable HTTP MCP server task."""
        from .server import run_server  # noqa: PLC0415

        assert self._mcp_server is not None
        if self._registrar is not None:
            self._registrar.apply_to_server(self._mcp_server)
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
        self._registrar = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
