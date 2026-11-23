"""Unit tests for `supernote.server.components.search.mcp`."""

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
from supernote.server.components.search import (
    SEARCH_SERVICE_KEY,
    NotebookInfo,
    SearchResult,
    SearchService,
)
from supernote.server.components.search.mcp import async_setup_mcp
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


async def _register_search_tools(
    component_core: ServerCore,
) -> tuple[McpRegistrar, MagicMock]:
    mock_search = MagicMock(spec=SearchService)
    mock_search.list_notebooks = AsyncMock(return_value=[])
    mock_search.search_chunks = AsyncMock(return_value=[])
    component_core.app[SEARCH_SERVICE_KEY] = mock_search
    registrar = McpRegistrar()
    await async_setup_mcp(component_core, registrar)
    return registrar, mock_search


async def test_search_mcp_list_notebooks_success_and_auth_failure(
    component_core: ServerCore,
    mcp_auth_user: None,
) -> None:
    """Verify `list_notebooks` registers via McpRegistrar and tracks metrics."""
    _ = mcp_auth_user
    registrar, mock_search = await _register_search_tools(component_core)
    assert registrar.tool_names == ("list_notebooks", "search_notebook_chunks")
    list_notebooks = registrar._tools["list_notebooks"]

    mock_search.list_notebooks.return_value = [
        NotebookInfo(
            file_id=101,
            file_name="Journal.note",
            create_time=1000,
            update_time=2000,
        )
    ]

    before_ok = _call_count("list_notebooks", "success")
    before_fail = _call_count("list_notebooks", "failure")
    before_dur = _duration_count("list_notebooks")

    ok_result = await list_notebooks(MagicMock(spec=Context), limit=10)
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "notebooks": [
            {
                "fileId": "101",
                "fileName": "Journal.note",
                "createTime": 1000,
                "updateTime": 2000,
            }
        ],
    }
    assert _call_count("list_notebooks", "success") == before_ok + 1.0
    assert _duration_count("list_notebooks") == before_dur + 1.0

    auth_context_var.set(None)
    err_result = await list_notebooks(MagicMock(spec=Context))
    assert err_result == {
        "success": False,
        "errorCode": "401",
        "errorMsg": "Authentication failed. Please set a valid token in meta.",
    }
    assert _call_count("list_notebooks", "failure") == before_fail + 1.0


async def test_search_mcp_search_notebook_chunks_success_and_auth_failure(
    component_core: ServerCore,
    mcp_auth_user: None,
) -> None:
    """Verify `search_notebook_chunks` serializes hits and handles auth errors."""
    _ = mcp_auth_user
    registrar, mock_search = await _register_search_tools(component_core)
    search_chunks = registrar._tools["search_notebook_chunks"]

    mock_search.search_chunks.return_value = [
        SearchResult(
            file_id=202,
            file_name="Roadmap.note",
            page_index=0,
            page_id="P20260101",
            score=0.92,
            text_preview="Q1 milestones",
            date="2026-01-01",
        )
    ]

    ok_result = await search_chunks(
        MagicMock(spec=Context),
        query="milestones",
        top_n=3,
        name_filter="Road",
        date_after="2026-01-01",
        date_before="2026-12-31",
    )
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "results": [
            {
                "fileId": "202",
                "fileName": "Roadmap.note",
                "pageIndex": 0,
                "pageId": "P20260101",
                "score": 0.92,
                "textPreview": "Q1 milestones",
                "date": "2026-01-01",
            }
        ],
    }

    auth_context_var.set(None)
    err_result = await search_chunks(MagicMock(spec=Context), query="milestones")
    assert err_result == {
        "success": False,
        "errorCode": "401",
        "errorMsg": "Authentication failed. Please set a valid token in meta.",
    }


async def test_search_mcp_tool_exception_and_cancellation_metrics(
    component_core: ServerCore,
    mcp_auth_user: None,
) -> None:
    """Verify exceptions record failure+duration and cancellations skip duration."""
    _ = mcp_auth_user
    registrar, mock_search = await _register_search_tools(component_core)
    search_chunks = registrar._tools["search_notebook_chunks"]

    mock_search.search_chunks.side_effect = RuntimeError("backend down")
    before_fail = _call_count("search_notebook_chunks", "failure")
    before_dur = _duration_count("search_notebook_chunks")
    with pytest.raises(RuntimeError, match="backend down"):
        await search_chunks(MagicMock(spec=Context), query="notes")
    assert _call_count("search_notebook_chunks", "failure") == before_fail + 1.0
    assert _duration_count("search_notebook_chunks") == before_dur + 1.0

    mock_search.search_chunks.side_effect = asyncio.CancelledError
    before_cancel = _call_count("search_notebook_chunks", "cancelled")
    before_dur2 = _duration_count("search_notebook_chunks")
    with pytest.raises(asyncio.CancelledError):
        await search_chunks(MagicMock(spec=Context), query="notes")
    assert _call_count("search_notebook_chunks", "cancelled") == before_cancel + 1.0
    assert _duration_count("search_notebook_chunks") == before_dur2
