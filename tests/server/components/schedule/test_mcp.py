"""MCP protocol tests for `supernote.server.components.schedule.mcp`."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.models.base import ErrorCode
from supernote.models.events import DomainEventType
from supernote.models.user import UserRegisterDTO
from supernote.server.events import ScheduleUpdatedEvent
from supernote.server.keys import EVENT_BUS_KEY
from supernote.server.services.user import UserService
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


@pytest.fixture
async def schedule_client(
    client: TestClient,
    auth_headers: dict[str, str],
) -> ScheduleClient:
    token = auth_headers["x-access-token"]

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    return ScheduleClient(
        Client(client.session, auth=TokenAuth(), host=str(client.make_url("")))
    )


async def test_schedule_mcp_registers_crud_tools(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert {"list_tasks", "create_task", "update_task", "delete_task"} <= names


async def test_schedule_mcp_requires_auth(mcp_url: str) -> None:
    async with httpx2.AsyncClient() as http_client:
        resp = await http_client.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401


async def test_create_list_update_delete_task_with_deep_link_and_filters(
    mcp_url: str,
    auth_headers: dict[str, str],
    schedule_client: ScheduleClient,
) -> None:
    group_res = await schedule_client.create_group(title="Work")
    assert group_res.task_list_id is not None
    group_id = group_res.task_list_id

    async with mcp_session(mcp_url, auth_headers) as session:
        created = await call_mcp_tool(
            session,
            "create_task",
            {
                "title": "Review Q4 roadmap",
                "detail": "Check milestones",
                "importance": "high",
                "due_time": 1700000000000,
                "group_id": group_id,
                "linked_file_id": "123456789",
                "linked_file_path": "/Note/Planning.note",
                "linked_page_id": "P20260101",
                "linked_page_number": 3,
            },
        )
        assert created["success"] is True
        task = created["task"]
        task_id = task["task_id"]
        assert task["title"] == "Review Q4 roadmap"
        assert task["group_id"] == group_id
        assert task["status"] == "needsAction"
        assert task["completed_time"] is None
        assert task["link"] == {
            "appName": "Note",
            "filePath": "/Note/Planning.note",
            "page": 3,
            "fileId": "123456789",
            "pageId": "P20260101",
            "taskTitle": "Review Q4 roadmap",
        }

        listed = await call_mcp_tool(session, "list_tasks", {"file_id": "123456789"})
        assert listed["success"] is True
        assert len(listed["groups"]) == 1
        assert listed["groups"][0]["group_id"] == group_id
        assert [t["task_id"] for t in listed["tasks"]] == [task_id]

        other_file = await call_mcp_tool(session, "list_tasks", {"file_id": "999999"})
        assert other_file["tasks"] == []

        updated = await call_mcp_tool(
            session,
            "update_task",
            {
                "task_id": task_id,
                "status": "completed",
                "linked_page_number": 4,
            },
        )
        assert updated["success"] is True
        assert updated["task"]["status"] == "completed"
        assert updated["task"]["completed_time"] is not None
        assert updated["task"]["link"]["fileId"] == "123456789"
        assert updated["task"]["link"]["page"] == 4

        active_only = await call_mcp_tool(session, "list_tasks", {})
        assert active_only["tasks"] == []
        with_completed = await call_mcp_tool(
            session, "list_tasks", {"include_completed": True}
        )
        assert [t["task_id"] for t in with_completed["tasks"]] == [task_id]

        reopened = await call_mcp_tool(
            session,
            "update_task",
            {
                "task_id": task_id,
                "status": "needsAction",
                "due_time": 0,
                "clear_link": True,
            },
        )
        assert reopened["task"]["status"] == "needsAction"
        assert reopened["task"]["completed_time"] is None
        assert reopened["task"]["due_time"] is None
        assert reopened["task"]["link"] is None

        deleted = await call_mcp_tool(session, "delete_task", {"task_id": task_id})
        assert deleted == {"success": True, "task_id": task_id}

        missing = await call_mcp_tool(session, "delete_task", {"task_id": task_id})
        assert missing["success"] is False
        assert missing["errorCode"] == ErrorCode.NOT_FOUND


async def test_schedule_mcp_enforces_user_isolation(
    mcp_url: str,
    auth_headers: dict[str, str],
    user_service: UserService,
) -> None:
    other_user = await user_service.register(
        UserRegisterDTO(email="other_mcp@example.com", password="a" * 32)
    )
    other_key, _ = await user_service.create_api_key(other_user.id, "Other MCP Client")
    other_headers = {"x-access-token": other_key}

    async with mcp_session(mcp_url, auth_headers) as session_a:
        created = await call_mcp_tool(
            session_a, "create_task", {"title": "User A secret"}
        )
        task_id = created["task"]["task_id"]

    async with mcp_session(mcp_url, other_headers) as session_b:
        listed = await call_mcp_tool(
            session_b, "list_tasks", {"include_completed": True}
        )
        assert listed["tasks"] == []

        upd = await call_mcp_tool(
            session_b, "update_task", {"task_id": task_id, "title": "Hijacked"}
        )
        assert upd["success"] is False
        assert upd["errorCode"] == ErrorCode.NOT_FOUND

        dele = await call_mcp_tool(session_b, "delete_task", {"task_id": task_id})
        assert dele["success"] is False
        assert dele["errorCode"] == ErrorCode.NOT_FOUND


async def test_schedule_mcp_records_event_provenance_and_task_syn(
    client: TestClient,
    mcp_url: str,
    user_service: UserService,
    test_user_id: int,
) -> None:
    assert client.app is not None
    schedule_events: list[ScheduleUpdatedEvent] = []

    async def _on_schedule_updated(ev: ScheduleUpdatedEvent) -> None:
        schedule_events.append(ev)

    client.app[EVENT_BUS_KEY].subscribe(
        ScheduleUpdatedEvent, _on_schedule_updated, inline=True
    )

    raw_key, key_vo = await user_service.create_api_key(
        test_user_id, "Magic Todo Agent"
    )
    api_key_headers = {"x-access-token": raw_key}

    async with mcp_session(mcp_url, api_key_headers) as session:
        created = await call_mcp_tool(
            session,
            "create_task",
            {
                "title": "Follow up with Alex",
                "linked_file_id": "5555",
                "linked_file_path": "/Note/Daily.note",
                "cause_seq": "9001",
                "reason": "Extracted from handwritten bullet",
            },
        )
        task_id = created["task"]["task_id"]

        await call_mcp_tool(
            session,
            "update_task",
            {
                "task_id": task_id,
                "status": "completed",
                "cause_seq": "9002",
                "reason": "Crossed off on page 2",
            },
        )
        await call_mcp_tool(
            session,
            "delete_task",
            {
                "task_id": task_id,
                "cause_seq": "9003",
                "reason": "Duplicate task pruned",
            },
        )

        page = await call_mcp_tool(
            session, "list_events", {"event_types": ["schedule.*"]}
        )

    assert len(schedule_events) == 3
    assert all(
        ev.user_id == test_user_id and ev.task_id == task_id for ev in schedule_events
    )

    events = page["events"]
    assert [e["eventType"] for e in events] == [
        DomainEventType.SCHEDULE_TASK_CREATED,
        DomainEventType.SCHEDULE_TASK_UPDATED,
        DomainEventType.SCHEDULE_TASK_DELETED,
    ]
    assert all(e["actor"] == f"api_key:{key_vo.id}" for e in events)
    assert all(e["relatedFileId"] == "5555" for e in events)
    assert events[0]["payload"]["cause_seq"] == "9001"
    assert events[0]["payload"]["reason"] == "Extracted from handwritten bullet"
    assert events[1]["payload"]["cause_seq"] == "9002"
    assert events[1]["payload"]["reason"] == "Crossed off on page 2"
    assert events[2]["payload"]["cause_seq"] == "9003"
    assert events[2]["payload"]["reason"] == "Duplicate task pruned"


@pytest.mark.parametrize(
    ("args", "expected_code"),
    [
        ({"title": "   "}, ErrorCode.BAD_REQUEST),
        ({"title": "Task", "status": "invalid"}, ErrorCode.BAD_REQUEST),
        ({"title": "Task", "linked_page_number": 0}, ErrorCode.BAD_REQUEST),
        ({"title": "Task", "group_id": "nonexistent-group"}, ErrorCode.NOT_FOUND),
    ],
)
async def test_create_task_validation_errors(
    mcp_url: str,
    auth_headers: dict[str, str],
    args: dict[str, Any],
    expected_code: ErrorCode,
) -> None:
    async with mcp_session(mcp_url, auth_headers) as session:
        resp = await call_mcp_tool(session, "create_task", args)
    assert resp["success"] is False
    assert resp["errorCode"] == expected_code


async def test_create_task_normalizes_zero_due_time(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    async with mcp_session(mcp_url, auth_headers) as session:
        created = await call_mcp_tool(
            session, "create_task", {"title": "Valid", "due_time": 0}
        )
    assert created["success"] is True
    assert created["task"]["due_time"] is None


@pytest.mark.parametrize(
    "update_args",
    [
        {"clear_link": True, "linked_file_id": "123"},
        {"title": "x" * 256},
    ],
)
async def test_update_task_validation_errors(
    mcp_url: str,
    auth_headers: dict[str, str],
    update_args: dict[str, Any],
) -> None:
    async with mcp_session(mcp_url, auth_headers) as session:
        created = await call_mcp_tool(session, "create_task", {"title": "Valid"})
        resp = await call_mcp_tool(
            session,
            "update_task",
            {"task_id": created["task"]["task_id"], **update_args},
        )
    assert resp["success"] is False
    assert resp["errorCode"] == ErrorCode.BAD_REQUEST


async def test_schedule_mcp_bounds_provenance_and_uses_token_actor(
    mcp_url: str,
    user_service: UserService,
    test_user_id: int,
) -> None:
    raw_key, key_vo = await user_service.create_api_key(test_user_id, "Bounded Agent")
    api_key_headers = {"x-access-token": raw_key}

    async with mcp_session(mcp_url, api_key_headers) as session:
        created = await call_mcp_tool(
            session,
            "create_task",
            {
                "title": "Bounded provenance task",
                "cause_seq": "1" * 100,
                "reason": "r" * 800,
            },
        )
        assert created["success"] is True

        page = await call_mcp_tool(
            session, "list_events", {"event_types": ["schedule.*"]}
        )

    assert len(page["events"]) == 1
    assert page["events"][0]["actor"] == f"api_key:{key_vo.id}"
    assert len(page["events"][0]["payload"]["cause_seq"]) == 64
    assert len(page["events"][0]["payload"]["reason"]) == 500
