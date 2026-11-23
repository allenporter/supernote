"""MCP protocol tests for `supernote.server.components.events.mcp`."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from supernote.server.components.events import EVENT_LOG_SERVICE_KEY
from supernote.server.services.user import UserService
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


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


async def test_events_mcp_list_events_pagination_and_filtering(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
) -> None:
    """Verify `list_events` supports cursor pagination, event_types, and file_id over MCP."""
    event_log = client.app[EVENT_LOG_SERVICE_KEY]
    ev1 = await event_log.append(
        user_id=test_user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="7001",
        related_file_id=7001,
        actor="device:SN001",
        payload={"path": "/NOTE/a.note"},
    )
    ev2 = await event_log.append(
        user_id=test_user_id,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="7001:0",
        related_file_id=7001,
        actor="system:processor",
        payload={"page_index": 0},
    )

    before_ok = _call_count("list_events", "success")
    before_dur = _duration_count("list_events")

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert "list_events" in {t.name for t in tools.tools}

        page1 = await call_mcp_tool(session, "list_events", {"limit": 1})
        assert page1["success"] is True
        assert [e["seq"] for e in page1["events"]] == [str(ev1.seq)]
        assert page1["hasMore"] is True
        assert page1["nextSyncToken"] is not None

        page2 = await call_mcp_tool(
            session, "list_events", {"sync_token": page1["nextSyncToken"]}
        )
        assert page2["success"] is True
        assert [e["seq"] for e in page2["events"]] == [str(ev2.seq)]
        assert page2["hasMore"] is False

        filtered = await call_mcp_tool(
            session,
            "list_events",
            {"event_types": ["note.*"], "file_id": "7001"},
        )
        assert filtered["success"] is True
        assert [e["seq"] for e in filtered["events"]] == [str(ev2.seq)]

    assert _call_count("list_events", "success") == before_ok + 3.0
    assert _duration_count("list_events") == before_dur + 3.0


async def test_events_mcp_exclude_self_echo_suppression(
    client: Any,
    mcp_url: str,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify case-insensitive `exclude_actors=['SELF']` omits the caller's own events."""
    raw_key, key_vo = await user_service.create_api_key(test_user_id, "Events Agent")
    event_log = client.app[EVENT_LOG_SERVICE_KEY]

    ev_human = await event_log.append(
        user_id=test_user_id,
        event_type="schedule.task_created",
        entity_type="schedule_task",
        entity_id="t1",
        actor="user:web",
    )
    ev_agent = await event_log.append(
        user_id=test_user_id,
        event_type="schedule.task_created",
        entity_type="schedule_task",
        entity_id="t2",
        actor=f"api_key:{key_vo.id}",
    )

    api_key_headers = {"x-access-token": raw_key}
    async with mcp_session(mcp_url, api_key_headers) as session:
        full = await call_mcp_tool(
            session, "list_events", {"event_types": ["schedule.*"]}
        )
        assert [e["seq"] for e in full["events"]] == [
            str(ev_human.seq),
            str(ev_agent.seq),
        ]

        filtered = await call_mcp_tool(
            session,
            "list_events",
            {"event_types": ["schedule.*"], "exclude_actors": ["SELF"]},
        )
        assert [e["seq"] for e in filtered["events"]] == [str(ev_human.seq)]


async def test_events_mcp_validation_and_expired_cursor_errors(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
) -> None:
    """Verify invalid params return 400 and pruned cursors return 410 Gone."""
    event_log = client.app[EVENT_LOG_SERVICE_KEY]
    old_ts = int(time.time() * 1000) - 60_000
    await event_log.append(
        user_id=test_user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=old_ts,
    )
    await event_log.append(
        user_id=test_user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="2",
        timestamp_ms=old_ts,
    )

    before_fail = _call_count("list_events", "failure")
    async with mcp_session(mcp_url, auth_headers) as session:
        bad_file_id = await call_mcp_tool(session, "list_events", {"file_id": "abc"})
        assert bad_file_id["success"] is False
        assert bad_file_id["errorCode"] == "400"

        bad_token = await call_mcp_tool(session, "list_events", {"sync_token": "bad"})
        assert bad_token["success"] is False
        assert bad_token["errorCode"] == "400"

        bad_limit = await call_mcp_tool(session, "list_events", {"limit": 0})
        assert bad_limit["success"] is False
        assert bad_limit["errorCode"] == "400"

        first_page = await call_mcp_tool(session, "list_events", {"limit": 1})
        stale_token = first_page["nextSyncToken"]
        assert stale_token is not None

        await event_log.prune_expired_events(max_age_ms=1_000)

        expired = await call_mcp_tool(
            session, "list_events", {"sync_token": stale_token}
        )
        assert expired["success"] is False
        assert expired["errorCode"] == "410"

    assert _call_count("list_events", "failure") == before_fail + 4.0


async def test_events_mcp_backend_error_records_failure_metric(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Verify unhandled EventLogService errors return MCP tool error and record failure."""
    before_fail = _call_count("list_events", "failure")
    before_dur = _duration_count("list_events")

    with patch.object(
        client.app[EVENT_LOG_SERVICE_KEY],
        "list_events",
        side_effect=RuntimeError("db failure"),
    ):
        async with mcp_session(mcp_url, auth_headers) as session:
            result = await session.call_tool("list_events", arguments={})

    assert result.is_error is True
    assert _call_count("list_events", "failure") == before_fail + 1.0
    assert _duration_count("list_events") == before_dur + 1.0
