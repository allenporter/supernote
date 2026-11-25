"""Unit tests for `supernote.server.components.mcp` (`McpComponent` and `McpRegistrar`)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from prometheus_client import REGISTRY

from supernote.server.components.mcp import (
    McpComponent,
    McpRegistrar,
    get_authenticated_user_id,
)
from supernote.server.components.oauth.models import SupernoteAccessToken
from supernote.server.core import Component, PlatformHost, ServerCore
from supernote.server.services.user import UserService
from tests.fixtures.server import pick_port
from tests.server.components.conftest import (
    LoadComponents,
    mcp_session,
    wait_for_mcp_server,
)


async def test_mcp_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
    user_service: UserService,
    test_user_id: int,
) -> None:
    component_core.config.host = "127.0.0.1"
    component_core.config.mcp_port = pick_port()

    loader = await load_components("mcp", start=False)
    component = loader.get("mcp")
    assert isinstance(component, McpComponent)
    assert isinstance(component, Component)
    assert isinstance(component, PlatformHost)
    assert component.domain == "mcp"
    assert component.dependencies == ("oauth",)
    assert component.platforms == ()
    assert component.hosted_platforms == ("mcp",)

    registrar = component.get_platform_registrar()
    assert isinstance(registrar, McpRegistrar)

    async def sample_tool() -> dict[str, Any]:
        return {"success": True}

    registrar.add_tool(sample_tool)

    await loader.async_start_all(component_core)
    try:
        url = await wait_for_mcp_server(
            component_core.config.host, component_core.config.mcp_port
        )
        raw_key, _ = await user_service.create_api_key(test_user_id, "Lifecycle Test")
        async with mcp_session(url, {"x-access-token": raw_key}) as session:
            tools = await session.list_tools()
            assert "sample_tool" in {t.name for t in tools.tools}
    finally:
        await loader.async_stop_all(component_core)
        await loader.async_stop_all(component_core)


async def test_mcp_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("mcp", start=False)
    await loader.async_stop_all(component_core)


async def test_mcp_component_rejects_invalid_config(
    load_components: LoadComponents,
) -> None:
    with pytest.raises(
        ValueError, match="mcp.port must be an integer between 0 and 65535"
    ):
        await load_components("mcp", configs={"mcp": {"port": -1}}, start=False)


def test_mcp_registrar_rejects_invalid_and_duplicate_names() -> None:
    registrar = McpRegistrar()

    async def ping_tool() -> dict[str, Any]:
        return {"success": True}

    registrar.add_tool(ping_tool, name="custom_ping")
    assert registrar.tool_names == ("custom_ping",)

    with pytest.raises(ValueError, match="already registered"):
        registrar.add_tool(ping_tool, name="custom_ping")

    with pytest.raises(ValueError, match="non-empty"):
        registrar.add_tool(ping_tool, name="   ")


async def test_mcp_registrar_apply_to_server_and_metrics() -> None:
    registrar = McpRegistrar()

    async def ping_tool(ok: bool = True) -> dict[str, Any]:
        return {"success": ok}

    registrar.add_tool(ping_tool, name="custom_ping")

    mcp = MCPServer("Test MCP")
    registrar.apply_to_server(mcp)
    registrar.apply_to_server(mcp)  # Idempotent

    tools = await mcp.list_tools()
    assert [t.name for t in tools] == ["custom_ping"]

    before_ok = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_ping", "status": "success"},
        )
        or 0.0
    )
    before_fail = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_ping", "status": "failure"},
        )
        or 0.0
    )

    await mcp.call_tool("custom_ping", {"ok": True})
    await mcp.call_tool("custom_ping", {"ok": False})

    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_ping", "status": "success"},
        )
        == before_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_ping", "status": "failure"},
        )
        == before_fail + 1.0
    )


async def test_mcp_registrar_tracks_call_tool_result_metrics() -> None:
    registrar = McpRegistrar()

    async def image_tool(ok: bool = True) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="ok" if ok else "err")],
            is_error=not ok,
        )

    registrar.add_tool(image_tool, name="custom_call_result")
    mcp = MCPServer("Test MCP")
    registrar.apply_to_server(mcp)

    before_ok = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_call_result", "status": "success"},
        )
        or 0.0
    )
    before_fail = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_call_result", "status": "failure"},
        )
        or 0.0
    )

    ok_res = await mcp.call_tool("custom_call_result", {"ok": True})
    fail_res = await mcp.call_tool("custom_call_result", {"ok": False})

    assert isinstance(ok_res, CallToolResult)
    assert isinstance(fail_res, CallToolResult)
    assert ok_res.is_error is False
    assert fail_res.is_error is True
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_call_result", "status": "success"},
        )
        == before_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "custom_call_result", "status": "failure"},
        )
        == before_fail + 1.0
    )


def test_get_authenticated_user_id() -> None:
    token = auth_context_var.set(None)
    try:
        assert get_authenticated_user_id() is None
        access_token = SupernoteAccessToken(
            token="tok",
            user_id=99,
            client_id="client",
            scopes=["supernote:all"],
        )
        auth_context_var.set(AuthenticatedUser(access_token))
        assert get_authenticated_user_id() == 99
    finally:
        auth_context_var.reset(token)


def test_importing_mcp_registrar_does_not_pull_in_oauth_component() -> None:
    """Platform modules importing `McpRegistrar` must not transitively import `oauth`."""
    check = (
        "import sys; "
        "from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m.startswith('supernote.server.components.oauth')"
        "); "
        "print(','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
