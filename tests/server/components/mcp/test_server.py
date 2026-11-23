"""Unit and integration tests for MCP server authentication, tool handlers, and metrics."""

import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.mcpserver import Context
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.models.user import UserRegisterDTO
from supernote.server.components.mcp import server as mcp_server_module
from supernote.server.components.mcp.models import SupernoteAccessToken
from supernote.server.components.mcp.server import (
    SupernoteTokenVerifier,
    _get_auth_user_id,
    create_mcp_server,
    create_task,
    delete_task,
    get_notebook_transcript,
    list_events,
    list_notebooks,
    list_tasks,
    search_notebook_chunks,
    set_services,
    update_task,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.metrics import (
    REQUEST_DURATION_BUCKETS,
    MCPToolName,
    init_mcp_metrics,
    track_mcp_tool_call,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.event_log import EventLogService, encode_sync_token
from supernote.server.services.schedule import ScheduleService
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
        user_id=42,
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
    """Verify `supernote_mcp_tool_duration_seconds` exports exact `REQUEST_DURATION_BUCKETS`."""
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
    assert finite_bounds == REQUEST_DURATION_BUCKETS
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


async def test_token_verifier_static_key_session_and_oauth(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Test SupernoteTokenVerifier handles OAuth tokens, static API keys, and session JWTs."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcpuser@example.com", password=pw_md5)
    )
    verifier = SupernoteTokenVerifier(user_service, coordination_service)

    assert await verifier.verify_token("sn_invalid_token_1234567890abcdef") is None
    assert await verifier.verify_token("") is None
    assert await verifier.verify_token("x" * 5000) is None

    # Valid static Bearer API key
    raw_token, key_vo = await user_service.create_api_key(
        user.id, "Test Verifier", expires_at=2_000_000_000
    )
    result = await verifier.verify_token(raw_token)
    assert result is not None
    assert result.user_id == user.id
    assert result.scopes == ["supernote:all"]
    assert result.client_id == "api_key"
    assert result.expires_at == 2_000_000_000

    # Revoked static Bearer API key
    await user_service.revoke_api_key(user.id, key_vo.id)
    assert await verifier.verify_token(raw_token) is None

    # Session JWT token
    session_jwt = await user_service.create_session("mcpuser@example.com")
    session_result = await verifier.verify_token(session_jwt)
    assert session_result is not None
    assert session_result.user_id == user.id
    assert session_result.client_id == "session"
    assert session_result.scopes == ["supernote:all"]

    # OAuth access token
    oauth_token = "oauth_token_xyz"
    oauth_data = {
        "user_id": user.id,
        "client_id": "oauth_client_1",
        "scopes": ["supernote:all"],
    }
    await coordination_service.set_value(
        f"mcp:access_token:{oauth_token}", json.dumps(oauth_data)
    )

    oauth_result = await verifier.verify_token(oauth_token)
    assert oauth_result is not None
    assert oauth_result.user_id == user.id
    assert oauth_result.client_id == "oauth_client_1"
    assert oauth_result.scopes == ["supernote:all"]

    # Legacy OAuth access token stored with email user_id migrates to int user_id
    legacy_token = "oauth_token_legacy_email"
    await coordination_service.set_value(
        f"mcp:access_token:{legacy_token}",
        json.dumps(
            {
                "user_id": "mcpuser@example.com",
                "client_id": "oauth_client_1",
                "scopes": ["supernote:all"],
            }
        ),
    )
    legacy_result = await verifier.verify_token(legacy_token)
    assert legacy_result is not None
    assert legacy_result.user_id == user.id

    # Legacy OAuth token for deleted/unknown user returns None
    unknown_legacy_token = "oauth_token_unknown_email"
    await coordination_service.set_value(
        f"mcp:access_token:{unknown_legacy_token}",
        json.dumps(
            {
                "user_id": "deleted@example.com",
                "client_id": "oauth_client_1",
                "scopes": ["supernote:all"],
            }
        ),
    )
    assert await verifier.verify_token(unknown_legacy_token) is None

    assert await verifier.verify_token("oauth_token_unknown") is None


async def test_get_auth_user_id() -> None:
    """Test _get_auth_user_id returns the integer user_id from the authenticated token."""
    previous_services = dict(mcp_server_module._services)
    mock_user_service = AsyncMock(spec=UserService)
    mock_search = AsyncMock(spec=SearchService)
    mock_coord = AsyncMock(spec=CoordinationService)
    set_services(mock_search, mock_user_service, mock_coord)
    try:
        ctx = AsyncMock(spec=Context)

        assert await _get_auth_user_id(ctx) is None

        token_user = SupernoteAccessToken(
            token="tok2",
            user_id=42,
            client_id="c1",
            scopes=["supernote:all"],
        )
        tok = auth_context_var.set(AuthenticatedUser(token_user))
        try:
            assert await _get_auth_user_id(ctx) == 42
        finally:
            auth_context_var.reset(tok)
    finally:
        mcp_server_module._services.clear()
        mcp_server_module._services.update(previous_services)


async def test_mcp_http_requests_authenticate_and_succeed(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Test MCP Streamable HTTP transport authentication with static Bearer keys."""
    previous_services = dict(mcp_server_module._services)
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcphttp@example.com", password=pw_md5)
    )
    mock_search_service = AsyncMock(spec=SearchService)
    mock_search_service.list_notebooks.return_value = []
    set_services(mock_search_service, user_service, coordination_service)

    try:
        raw_token, key_vo = await user_service.create_api_key(user.id, "MCP Key")

        mcp = create_mcp_server(
            issuer_url="http://localhost:8080",
            resource_server_url="http://localhost:8080/mcp",
        )
        app = mcp.streamable_http_app()

        with TestClient(app, base_url="http://localhost:8080") as client:
            unauth_resp = client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
            )
            assert unauth_resp.status_code == 401

            invalid_resp = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                headers={"Authorization": "Bearer sn_invalidtoken1234567890abcdef0123"},
            )
            assert invalid_resp.status_code == 401

            init_body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            }
            init_resp = client.post(
                "/mcp",
                json=init_body,
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert init_resp.status_code == 200
            session_id = init_resp.headers.get("mcp-session-id")

            headers = {"Authorization": f"Bearer {raw_token}"}
            if session_id:
                headers["mcp-session-id"] = session_id

            tool_resp = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "list_notebooks", "arguments": {}},
                },
                headers=headers,
            )
            assert tool_resp.status_code == 200
            assert "notebooks" in tool_resp.text

            await user_service.revoke_api_key(user.id, key_vo.id)
            revoked_resp = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 3, "method": "initialize"},
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert revoked_resp.status_code == 401
    finally:
        mcp_server_module._services.clear()
        mcp_server_module._services.update(previous_services)


@dataclass
class MCPScheduleTestEnv:
    """Real ScheduleService + EventLogService harness for MCP schedule/event tool tests."""

    ctx: Context
    schedule_service: ScheduleService
    event_log_service: EventLogService
    user_id: int
    other_token: SupernoteAccessToken


@pytest.fixture
def mcp_schedule_env(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    user_service: UserService,
) -> Generator[MCPScheduleTestEnv]:
    """Wire real ScheduleService and EventLogService into MCP with an OAuth bearer token."""
    previous_services = dict(mcp_server_module._services)
    event_bus = LocalEventBus()
    schedule_service = ScheduleService(session_manager, event_bus=event_bus)
    event_log_service = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        event_bus=event_bus,
    )
    set_services(
        MagicMock(spec=SearchService),
        user_service,
        coordination_service,
        schedule_service=schedule_service,
        event_log_service=event_log_service,
    )

    user1_token = SupernoteAccessToken(
        token="mcp-oauth-tok",
        user_id=701,
        client_id="magic-todo-client",
        scopes=["supernote:all"],
        actor="oauth:magic-todo-client",
    )
    user2_token = SupernoteAccessToken(
        token="mcp-other-tok",
        user_id=702,
        client_id="other-client",
        scopes=["supernote:all"],
        actor="oauth:other-client",
    )
    ctx_token = auth_context_var.set(AuthenticatedUser(user1_token))
    try:
        yield MCPScheduleTestEnv(
            ctx=MagicMock(spec=Context),
            schedule_service=schedule_service,
            event_log_service=event_log_service,
            user_id=701,
            other_token=user2_token,
        )
    finally:
        auth_context_var.reset(ctx_token)
        mcp_server_module._services.clear()
        mcp_server_module._services.update(previous_services)


async def test_mcp_schedule_create_list_and_delete_with_deep_link(
    mcp_schedule_env: MCPScheduleTestEnv,
) -> None:
    """Verify create_task, list_tasks filtering (file_id, include_completed), and delete_task."""
    env = mcp_schedule_env
    group = await env.schedule_service.create_group(env.user_id, "Daily")
    human_task = await env.schedule_service.create_task(
        env.user_id, group_id=group.task_list_id, title="Human task"
    )

    created = await create_task(
        env.ctx,
        title="Buy coffee beans",
        detail="From Daily.note",
        due_time=0,
        group_id=group.task_list_id,
        linked_file_id="9001",
        linked_file_path="/Note/Daily.note",
        linked_page_id="P20261123090500abc",
        linked_page_number=2,
    )
    assert created["success"] is True
    assert created["task"]["dueTime"] is None
    task_id = created["task"]["taskId"]
    assert created["task"]["link"] == {
        "appName": "Note",
        "filePath": "/Note/Daily.note",
        "page": 2,
        "fileId": "9001",
        "pageId": "P20261123090500abc",
        "taskTitle": None,
    }

    linked_list = await list_tasks(env.ctx, file_id="9001")
    assert linked_list["success"] is True
    assert [t["taskId"] for t in linked_list["tasks"]] == [task_id]
    assert [g["taskListId"] for g in linked_list["groups"]] == [group.task_list_id]

    deleted = await delete_task(env.ctx, task_id=task_id)
    assert deleted["success"] is True
    assert deleted["deleted"] is True
    assert [t["taskId"] for t in (await list_tasks(env.ctx))["tasks"]] == [
        human_task.task_id
    ]


async def test_mcp_update_task_preserves_task_title_completed_time_and_handles_malformed_link(
    mcp_schedule_env: MCPScheduleTestEnv,
) -> None:
    """Verify partial link updates preserve task_title, repeated completion preserves completed_time, and malformed links do not crash list_tasks."""
    env = mcp_schedule_env
    tablet_link = ScheduleTaskLinkDTO(
        app_name="Note",
        path="/Note/Daily.note",
        page=1,
        file_id="9001",
        page_id="P1",
        task_title="Tablet Title",
    ).to_b64()
    task = await env.schedule_service.create_task(
        env.user_id, title="Migrate me", links=tablet_link
    )
    bad_link = base64.b64encode(b"{}").decode("ascii")
    await env.schedule_service.create_task(
        env.user_id, title="Corrupt link task", links=bad_link
    )

    listed = await list_tasks(env.ctx)
    assert listed["success"] is True
    assert len(listed["tasks"]) == 2

    completed = await update_task(
        env.ctx,
        task_id=task.task_id,
        status="completed",
        linked_page_number=3,
    )
    assert completed["success"] is True
    first_completed_ms = completed["task"]["completedTime"]
    assert first_completed_ms is not None
    assert completed["task"]["link"]["page"] == 3
    assert completed["task"]["link"]["taskTitle"] == "Tablet Title"

    completed_again = await update_task(
        env.ctx, task_id=task.task_id, status="completed"
    )
    assert completed_again["task"]["completedTime"] == first_completed_ms

    reopened = await update_task(
        env.ctx, task_id=task.task_id, status="needsAction", clear_link=True
    )
    assert reopened["success"] is True
    assert reopened["task"]["completedTime"] is None
    assert reopened["task"]["link"] is None


async def test_mcp_schedule_and_events_enforce_user_isolation(
    mcp_schedule_env: MCPScheduleTestEnv,
) -> None:
    """Verify another user cannot read, update, delete, or view events for user 701's tasks."""
    env = mcp_schedule_env
    created = await create_task(env.ctx, title="Private task")
    task_id = created["task"]["taskId"]

    other_tok = auth_context_var.set(AuthenticatedUser(env.other_token))
    try:
        assert (await list_tasks(env.ctx, include_completed=True))["tasks"] == []
        assert (await update_task(env.ctx, task_id=task_id, title="Hijack"))[
            "success"
        ] is False
        assert (await delete_task(env.ctx, task_id=task_id))["success"] is False
        assert (await list_events(env.ctx))["events"] == []
    finally:
        auth_context_var.reset(other_tok)


async def test_mcp_list_events_suppresses_self_echo_and_reports_expired_cursor(
    mcp_schedule_env: MCPScheduleTestEnv,
) -> None:
    """Verify list_events supports exclude_actors=['self'] and maps CursorExpiredError to errorCode 410."""
    env = mcp_schedule_env
    human_task = await env.schedule_service.create_task(env.user_id, title="Human task")
    created = await create_task(env.ctx, title="Agent task")
    await delete_task(env.ctx, task_id=created["task"]["taskId"])

    all_events = await list_events(env.ctx, event_types=["schedule.*"])
    assert [(e["eventType"], e["actor"]) for e in all_events["events"]] == [
        ("schedule.task_created", "user:web"),
        ("schedule.task_created", "oauth:magic-todo-client"),
        ("schedule.task_deleted", "oauth:magic-todo-client"),
    ]

    filtered = await list_events(
        env.ctx, event_types=["schedule.*"], exclude_actors=["self"]
    )
    assert [(e["entityId"], e["actor"]) for e in filtered["events"]] == [
        (human_task.task_id, "user:web")
    ]

    # Prune old events so an older sync_token triggers CursorExpiredError -> errorCode "410"
    old_ev = await env.event_log_service.append(
        user_id=env.user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=1_000,
    )
    await env.event_log_service.prune_expired_events(max_age_ms=1_000)
    expired = await list_events(env.ctx, sync_token=encode_sync_token(old_ev.seq - 1))
    assert expired["success"] is False
    assert expired["errorCode"] == "410"


@pytest.mark.parametrize(
    ("tool_fn", "kwargs"),
    [
        (create_task, {"title": "Bad", "status": "invalid"}),
        (create_task, {"title": "Bad", "linked_page_number": 0}),
        (create_task, {"title": "Bad", "due_time": -1}),
        (list_events, {"file_id": "not-a-number"}),
        (list_events, {"sync_token": "bad-token"}),
    ],
)
async def test_mcp_schedule_and_events_reject_invalid_inputs(
    mcp_schedule_env: MCPScheduleTestEnv,
    tool_fn: Callable[..., Awaitable[dict[str, Any]]],
    kwargs: dict[str, Any],
) -> None:
    """Verify invalid parameters return structured 400 error responses."""
    res = await tool_fn(mcp_schedule_env.ctx, **kwargs)
    assert res["success"] is False
    assert res["errorCode"] == "400"


async def test_mcp_update_task_rejects_empty_and_conflicting_link_args(
    mcp_schedule_env: MCPScheduleTestEnv,
) -> None:
    """Verify update_task rejects empty updates, conflicting clear_link, and oversized titles."""
    env = mcp_schedule_env
    created = await create_task(env.ctx, title="Valid")
    task_id = created["task"]["taskId"]

    assert (await update_task(env.ctx, task_id=task_id))["errorCode"] == "400"
    assert (
        await update_task(
            env.ctx, task_id=task_id, clear_link=True, linked_file_id="123"
        )
    )["errorCode"] == "400"
    assert (await update_task(env.ctx, task_id=task_id, title="x" * 300))[
        "errorCode"
    ] == "400"


async def test_supernote_token_verifier_populates_actor(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Verify SupernoteTokenVerifier populates canonical actor for OAuth and API key tokens."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcpactor@example.com", password=pw_md5)
    )
    verifier = SupernoteTokenVerifier(user_service, coordination_service)

    await coordination_service.set_value(
        "mcp:access_token:oauth_tok_actor",
        json.dumps(
            {
                "token": "oauth_tok_actor",
                "user_id": user.id,
                "client_id": "claude-desktop",
                "scopes": ["supernote:all"],
            }
        ),
        ttl=3600,
    )
    oauth_tok = await verifier.verify_token("oauth_tok_actor")
    assert oauth_tok is not None
    assert oauth_tok.actor == "oauth:claude-desktop"

    raw_key, key_vo = await user_service.create_api_key(user.id, "MCP Agent")
    key_tok = await verifier.verify_token(raw_key)
    assert key_tok is not None
    assert key_tok.actor == f"api_key:{key_vo.id}"
