"""Unit tests for MCP server tool handlers and Prometheus instrumentation."""

import asyncio
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.mcpserver import Context
from prometheus_client import REGISTRY

from supernote.server.mcp import server as mcp_server_module
from supernote.server.mcp.models import SupernoteAccessToken
from supernote.server.mcp.server import (
    create_mcp_server,
    get_notebook_transcript,
    list_notebooks,
    search_notebook_chunks,
    set_services,
)
from supernote.server.metrics import (
    MCP_TOOL_DURATION_BUCKETS,
    MCPToolName,
    init_mcp_metrics,
    track_mcp_tool_call,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.search import NotebookInfo, SearchResult, SearchService
from supernote.server.services.user import UserService


@dataclass
class MCPToolTestEnv:
    """Isolated service and auth-context test harness for MCP tool handlers."""

    ctx: Context
    search_service: MagicMock
    user_service: MagicMock
    coordination_service: MagicMock

    def clear_auth(self) -> None:
        """Clear the active MCP bearer authentication context."""
        auth_context_var.set(None)


def _call_count(tool: MCPToolName, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": tool.value, "status": status},
        )
        or 0.0
    )


def _duration_count(tool: MCPToolName) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": tool.value},
        )
        or 0.0
    )


@pytest.fixture
def mcp_env() -> Generator[MCPToolTestEnv]:
    """Configure mocked MCP services and authenticated user context with clean teardown."""
    previous_services = dict(mcp_server_module._services)
    search_service = MagicMock(spec=SearchService)
    search_service.list_notebooks = AsyncMock(return_value=[])
    search_service.search_chunks = AsyncMock(return_value=[])
    search_service.get_transcript = AsyncMock(return_value="Transcript body")

    user_service = MagicMock(spec=UserService)
    user_service.get_user_id = AsyncMock(return_value=42)

    coordination_service = MagicMock(spec=CoordinationService)
    set_services(search_service, user_service, coordination_service)

    access_token = SupernoteAccessToken(
        token="test-mcp-token",
        user_id="test@example.com",
        client_id="https://client.example.com",
        scopes=["supernote:all"],
    )
    ctx_token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        yield MCPToolTestEnv(
            ctx=MagicMock(spec=Context),
            search_service=search_service,
            user_service=user_service,
            coordination_service=coordination_service,
        )
    finally:
        auth_context_var.reset(ctx_token)
        mcp_server_module._services.clear()
        mcp_server_module._services.update(previous_services)


async def test_create_mcp_server_seeds_metrics_and_registers_tools(
    mcp_env: MCPToolTestEnv,
) -> None:
    """Verify `create_mcp_server` pre-seeds tool counters at >= 0 and registers all tools."""
    mcp = create_mcp_server(
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081/mcp",
    )
    registered_tools = await mcp.list_tools()
    assert {t.name for t in registered_tools} == {t.value for t in MCPToolName}

    init_mcp_metrics()
    for tool in MCPToolName:
        for status in ("success", "failure"):
            val = REGISTRY.get_sample_value(
                "supernote_mcp_tool_calls_total",
                {"tool": tool.value, "status": status},
            )
            assert val is not None and val >= 0.0


async def test_mcp_tool_duration_histogram_buckets(
    mcp_env: MCPToolTestEnv,
) -> None:
    """Verify `supernote_mcp_tool_duration_seconds` exports exact `MCP_TOOL_DURATION_BUCKETS`."""
    await list_notebooks(mcp_env.ctx)

    metric_families = {
        family.name: family
        for family in REGISTRY.collect()
        if family.name == "supernote_mcp_tool_duration_seconds"
    }
    assert "supernote_mcp_tool_duration_seconds" in metric_families
    family = metric_families["supernote_mcp_tool_duration_seconds"]
    finite_bounds = tuple(
        float(sample.labels["le"])
        for sample in family.samples
        if sample.name == "supernote_mcp_tool_duration_seconds_bucket"
        and sample.labels.get("tool") == MCPToolName.LIST_NOTEBOOKS.value
        and sample.labels["le"] != "+Inf"
    )
    assert finite_bounds == MCP_TOOL_DURATION_BUCKETS
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_bucket",
            {"tool": MCPToolName.LIST_NOTEBOOKS.value, "le": "+Inf"},
        )
        is not None
    )


async def test_list_notebooks_success_and_error_metrics(
    mcp_env: MCPToolTestEnv,
) -> None:
    """Verify `list_notebooks` tracks both successful calls and error-dict responses."""
    tool = MCPToolName.LIST_NOTEBOOKS
    mcp_env.search_service.list_notebooks.return_value = [
        NotebookInfo(
            file_id=101,
            file_name="daily.note",
            create_time=1000,
            update_time=2000,
        )
    ]

    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_dur = _duration_count(tool)

    ok_result = await list_notebooks(mcp_env.ctx, limit=10, name_filter="daily")
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "notebooks": [
            {
                "fileId": "101",
                "fileName": "daily.note",
                "createTime": 1000,
                "updateTime": 2000,
            }
        ],
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail
    assert _duration_count(tool) == before_dur + 1.0

    # Unauthenticated response returns {"success": False, ...} -> status="failure" + duration
    mcp_env.clear_auth()
    err_result = await list_notebooks(mcp_env.ctx)
    assert err_result == {
        "success": False,
        "errorCode": "401",
        "errorMsg": "Authentication failed. Please set a valid token in meta.",
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail + 1.0
    assert _duration_count(tool) == before_dur + 2.0


async def test_search_notebook_chunks_success_and_error_metrics(
    mcp_env: MCPToolTestEnv,
) -> None:
    """Verify `search_notebook_chunks` tracks both successful calls and error-dict responses."""
    tool = MCPToolName.SEARCH_NOTEBOOK_CHUNKS
    mcp_env.search_service.search_chunks.return_value = [
        SearchResult(
            file_id=101,
            file_name="daily.note",
            page_index=0,
            page_id="P001",
            score=0.95,
            text_preview="Project roadmap",
            date="2026-11-09",
        )
    ]

    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_dur = _duration_count(tool)

    ok_result = await search_notebook_chunks(mcp_env.ctx, query="roadmap", top_n=3)
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "results": [
            {
                "fileId": "101",
                "fileName": "daily.note",
                "pageIndex": 0,
                "pageId": "P001",
                "score": 0.95,
                "textPreview": "Project roadmap",
                "date": "2026-11-09",
            }
        ],
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail
    assert _duration_count(tool) == before_dur + 1.0

    # Unauthenticated response returns {"success": False, ...} -> status="failure" + duration
    mcp_env.clear_auth()
    err_result = await search_notebook_chunks(mcp_env.ctx, query="roadmap")
    assert err_result == {
        "success": False,
        "errorCode": "401",
        "errorMsg": "Authentication failed. Please set a valid token in meta.",
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail + 1.0
    assert _duration_count(tool) == before_dur + 2.0


async def test_get_notebook_transcript_success_and_error_metrics(
    mcp_env: MCPToolTestEnv,
) -> None:
    """Verify `get_notebook_transcript` tracks success, invalid ID, and not-found responses."""
    tool = MCPToolName.GET_NOTEBOOK_TRANSCRIPT
    mcp_env.search_service.get_transcript.return_value = "Page 1 transcript"

    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_dur = _duration_count(tool)

    ok_result = await get_notebook_transcript(mcp_env.ctx, file_id="101")
    assert ok_result == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "transcript": "Page 1 transcript",
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail
    assert _duration_count(tool) == before_dur + 1.0

    # Non-numeric file_id returns {"success": False, ...} -> status="failure" + duration
    bad_id_result = await get_notebook_transcript(mcp_env.ctx, file_id="abc")
    assert bad_id_result == {
        "success": False,
        "errorCode": "400",
        "errorMsg": "Invalid file_id 'abc': must be a numeric ID string.",
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail + 1.0
    assert _duration_count(tool) == before_dur + 2.0

    # Missing transcript returns {"success": False, ...} -> status="failure" + duration
    mcp_env.search_service.get_transcript.return_value = None
    not_found_result = await get_notebook_transcript(mcp_env.ctx, file_id="999")
    assert not_found_result == {
        "success": False,
        "errorCode": "404",
        "errorMsg": "No transcript found for notebook 999.",
    }
    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail + 2.0
    assert _duration_count(tool) == before_dur + 3.0


@pytest.mark.parametrize(
    ("tool", "service_method", "invoke"),
    [
        (
            MCPToolName.LIST_NOTEBOOKS,
            "list_notebooks",
            lambda ctx: list_notebooks(ctx),
        ),
        (
            MCPToolName.SEARCH_NOTEBOOK_CHUNKS,
            "search_chunks",
            lambda ctx: search_notebook_chunks(ctx, query="notes"),
        ),
        (
            MCPToolName.GET_NOTEBOOK_TRANSCRIPT,
            "get_transcript",
            lambda ctx: get_notebook_transcript(ctx, file_id="101"),
        ),
    ],
)
async def test_mcp_tools_unhandled_exception_records_failure_and_duration(
    mcp_env: MCPToolTestEnv,
    tool: MCPToolName,
    service_method: str,
    invoke: Callable[[Context], Awaitable[dict[str, Any]]],
) -> None:
    """Verify unhandled exceptions increment `status='failure'`, observe latency, and propagate."""
    getattr(mcp_env.search_service, service_method).side_effect = RuntimeError(
        "unexpected backend failure"
    )

    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_cancel = _call_count(tool, "cancelled")
    before_dur = _duration_count(tool)

    with pytest.raises(RuntimeError, match="unexpected backend failure"):
        await invoke(mcp_env.ctx)

    assert _call_count(tool, "success") == before_ok
    assert _call_count(tool, "failure") == before_fail + 1.0
    assert _call_count(tool, "cancelled") == before_cancel
    assert _duration_count(tool) == before_dur + 1.0


@pytest.mark.parametrize(
    ("tool", "service_method", "invoke"),
    [
        (
            MCPToolName.LIST_NOTEBOOKS,
            "list_notebooks",
            lambda ctx: list_notebooks(ctx),
        ),
        (
            MCPToolName.SEARCH_NOTEBOOK_CHUNKS,
            "search_chunks",
            lambda ctx: search_notebook_chunks(ctx, query="notes"),
        ),
        (
            MCPToolName.GET_NOTEBOOK_TRANSCRIPT,
            "get_transcript",
            lambda ctx: get_notebook_transcript(ctx, file_id="101"),
        ),
    ],
)
async def test_mcp_tools_cancellation_skips_duration_and_propagates(
    mcp_env: MCPToolTestEnv,
    tool: MCPToolName,
    service_method: str,
    invoke: Callable[[Context], Awaitable[dict[str, Any]]],
) -> None:
    """Verify `CancelledError` increments `status='cancelled'`, skips latency, and propagates."""
    getattr(mcp_env.search_service, service_method).side_effect = asyncio.CancelledError

    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_cancel = _call_count(tool, "cancelled")
    before_dur = _duration_count(tool)

    with pytest.raises(asyncio.CancelledError):
        await invoke(mcp_env.ctx)

    assert _call_count(tool, "success") == before_ok
    assert _call_count(tool, "failure") == before_fail
    assert _call_count(tool, "cancelled") == before_cancel + 1.0
    assert _duration_count(tool) == before_dur


def test_track_mcp_tool_call_cancelled_after_set_succeeded() -> None:
    """Verify cancellation still overrides a prior `set_succeeded(True)` without observing latency."""
    tool = MCPToolName.LIST_NOTEBOOKS
    before_ok = _call_count(tool, "success")
    before_cancel = _call_count(tool, "cancelled")
    before_dur = _duration_count(tool)

    with pytest.raises(asyncio.CancelledError):
        with track_mcp_tool_call(tool=tool) as call:
            call.set_succeeded(True)
            raise asyncio.CancelledError

    assert _call_count(tool, "success") == before_ok
    assert _call_count(tool, "cancelled") == before_cancel + 1.0
    assert _duration_count(tool) == before_dur
