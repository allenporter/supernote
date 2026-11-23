"""Unit tests for `supernote.server.components.transcript.mcp`."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.mcpserver import Context
from prometheus_client import REGISTRY

from supernote.server.components.mcp import McpRegistrar
from supernote.server.components.oauth.models import SupernoteAccessToken
from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    TranscriptService,
)
from supernote.server.components.transcript.mcp import async_setup_mcp
from supernote.server.core import ServerCore


def _call_count(tool: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": tool, "status": status},
        )
        or 0.0
    )


def _duration_count(tool: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": tool},
        )
        or 0.0
    )


@pytest.fixture
def mcp_auth_user() -> Generator[None]:
    """Bind an authenticated MCP bearer user context for tool handler tests."""
    token = SupernoteAccessToken(
        token="test-mcp-token",
        user_id=42,
        client_id="https://client.example.com",
        scopes=["supernote:all"],
    )
    ctx_token = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(ctx_token)


async def _register_transcript_tool(
    component_core: ServerCore,
) -> tuple[McpRegistrar, MagicMock]:
    mock_transcript = MagicMock(spec=TranscriptService)
    mock_transcript.get_transcript = AsyncMock(return_value="Page 1 transcript")
    component_core.app[TRANSCRIPT_SERVICE_KEY] = mock_transcript
    registrar = McpRegistrar()
    await async_setup_mcp(component_core, registrar)
    return registrar, mock_transcript


async def test_transcript_mcp_success_and_error_responses(
    component_core: ServerCore,
    mcp_auth_user: None,
) -> None:
    """Verify `get_notebook_transcript` handles success, 400, 404, and 401 paths."""
    _ = mcp_auth_user
    registrar, mock_transcript = await _register_transcript_tool(component_core)
    assert registrar.tool_names == ("get_notebook_transcript",)
    get_transcript = registrar._tools["get_notebook_transcript"]

    before_ok = _call_count("get_notebook_transcript", "success")
    before_fail = _call_count("get_notebook_transcript", "failure")
    before_dur = _duration_count("get_notebook_transcript")

    ok_result = await get_transcript(MagicMock(spec=Context), file_id="101")
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "transcript": "Page 1 transcript",
    }
    assert _call_count("get_notebook_transcript", "success") == before_ok + 1.0
    assert _duration_count("get_notebook_transcript") == before_dur + 1.0

    bad_id = await get_transcript(MagicMock(spec=Context), file_id="abc")
    assert bad_id == {
        "success": False,
        "errorCode": "400",
        "errorMsg": "Invalid file_id 'abc': must be a numeric ID string.",
    }

    mock_transcript.get_transcript.return_value = None
    not_found = await get_transcript(MagicMock(spec=Context), file_id="999")
    assert not_found == {
        "success": False,
        "errorCode": "404",
        "errorMsg": "No transcript found for notebook 999.",
    }

    auth_context_var.set(None)
    unauth = await get_transcript(MagicMock(spec=Context), file_id="101")
    assert unauth == {
        "success": False,
        "errorCode": "401",
        "errorMsg": "Authentication failed. Please set a valid token in meta.",
    }
    assert _call_count("get_notebook_transcript", "failure") == before_fail + 3.0


async def test_transcript_mcp_exception_and_cancellation_metrics(
    component_core: ServerCore,
    mcp_auth_user: None,
) -> None:
    """Verify unhandled errors and cancellations update metrics appropriately."""
    _ = mcp_auth_user
    registrar, mock_transcript = await _register_transcript_tool(component_core)
    get_transcript = registrar._tools["get_notebook_transcript"]

    mock_transcript.get_transcript.side_effect = RuntimeError("db error")
    before_fail = _call_count("get_notebook_transcript", "failure")
    with pytest.raises(RuntimeError, match="db error"):
        await get_transcript(MagicMock(spec=Context), file_id="101")
    assert _call_count("get_notebook_transcript", "failure") == before_fail + 1.0

    mock_transcript.get_transcript.side_effect = asyncio.CancelledError
    before_cancel = _call_count("get_notebook_transcript", "cancelled")
    before_dur = _duration_count("get_notebook_transcript")
    with pytest.raises(asyncio.CancelledError):
        await get_transcript(MagicMock(spec=Context), file_id="101")
    assert _call_count("get_notebook_transcript", "cancelled") == before_cancel + 1.0
    assert _duration_count("get_notebook_transcript") == before_dur
