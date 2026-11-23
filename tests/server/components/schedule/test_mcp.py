"""Unit and integration tests for `supernote.server.components.schedule.mcp`."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from typing import Any

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from supernote.models.base import ErrorCode
from supernote.models.events import DomainEventType
from supernote.server.components.events.service import EventLogService
from supernote.server.components.mcp import McpRegistrar
from supernote.server.components.oauth.models import SupernoteAccessToken
from supernote.server.components.schedule import (
    SCHEDULE_SERVICE_KEY,
    ScheduleComponent,
    ScheduleService,
)
from supernote.server.components.schedule.mcp import async_setup_mcp
from supernote.server.core import ComponentLoader, ServerCore
from supernote.server.events import ScheduleUpdatedEvent


@contextmanager
def _mcp_user(
    user_id: int | None,
    client_id: str = "magic-todo-agent",
    actor: str | None = None,
) -> Generator[None]:
    """Bind an authenticated (or unauthenticated) MCP user context for the block."""
    if user_id is None:
        ctx_token = auth_context_var.set(None)
    else:
        token = SupernoteAccessToken(
            token=f"tok-{user_id}",
            user_id=user_id,
            client_id=client_id,
            scopes=["supernote:all"],
            actor=actor if actor is not None else f"oauth:{client_id}",
        )
        ctx_token = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(ctx_token)


async def _call_tool(mcp: MCPServer, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(name, args)
    assert isinstance(result, CallToolResult)
    if result.structured_content is not None:
        return dict(result.structured_content)
    block = result.content[0]
    assert isinstance(block, TextContent)
    return json.loads(block.text)


@pytest.fixture
async def schedule_mcp(
    component_core: ServerCore,
) -> AsyncGenerator[tuple[MCPServer, ScheduleService, EventLogService]]:
    """Wire ScheduleComponent + EventLogService + McpRegistrar onto an MCPServer."""
    event_log = EventLogService(
        session_manager=component_core.session_manager,
        coordination_service=component_core.coordination,
        event_bus=component_core.event_bus,
    )
    loader = ComponentLoader()
    loader.register(ScheduleComponent())
    await loader.async_setup_all(component_core, {})

    registrar = McpRegistrar()
    await async_setup_mcp(component_core, registrar)

    mcp = MCPServer("Schedule Test MCP")
    registrar.apply_to_server(mcp)
    try:
        yield mcp, component_core.app[SCHEDULE_SERVICE_KEY], event_log
    finally:
        await loader.async_stop_all(component_core)


async def test_schedule_mcp_registers_crud_tools(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, _, _ = schedule_mcp
    names = [t.name for t in await mcp.list_tools()]
    assert names == ["list_tasks", "create_task", "update_task", "delete_task"]


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("list_tasks", {}),
        ("create_task", {"title": "Buy milk"}),
        ("update_task", {"task_id": "t1", "title": "Updated"}),
        ("delete_task", {"task_id": "t1"}),
    ],
)
async def test_schedule_mcp_tools_require_auth(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
    tool_name: str,
    args: dict[str, Any],
) -> None:
    mcp, _, _ = schedule_mcp
    with _mcp_user(None):
        resp = await _call_tool(mcp, tool_name, args)
    assert resp["success"] is False
    assert resp["errorCode"] == ErrorCode.UNAUTHORIZED


async def test_create_list_update_delete_task_with_deep_link_and_filters(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, schedule_service, _ = schedule_mcp
    group = await schedule_service.create_group(user_id=101, title="Work")

    with _mcp_user(101):
        created = await _call_tool(
            mcp,
            "create_task",
            {
                "title": "Review Q4 roadmap",
                "detail": "Check milestones",
                "importance": "high",
                "due_time": 1700000000000,
                "group_id": group.task_list_id,
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
        assert task["group_id"] == group.task_list_id
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

        listed = await _call_tool(mcp, "list_tasks", {"file_id": "123456789"})
        assert listed["success"] is True
        assert len(listed["groups"]) == 1
        assert listed["groups"][0]["group_id"] == group.task_list_id
        assert [t["task_id"] for t in listed["tasks"]] == [task_id]

        other_file = await _call_tool(mcp, "list_tasks", {"file_id": "999999"})
        assert other_file["tasks"] == []

        updated = await _call_tool(
            mcp,
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

        active_only = await _call_tool(mcp, "list_tasks", {})
        assert active_only["tasks"] == []
        with_completed = await _call_tool(
            mcp, "list_tasks", {"include_completed": True}
        )
        assert [t["task_id"] for t in with_completed["tasks"]] == [task_id]

        reopened = await _call_tool(
            mcp,
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

        deleted = await _call_tool(mcp, "delete_task", {"task_id": task_id})
        assert deleted == {"success": True, "task_id": task_id}

        missing = await _call_tool(mcp, "delete_task", {"task_id": task_id})
        assert missing["success"] is False
        assert missing["errorCode"] == ErrorCode.NOT_FOUND


async def test_schedule_mcp_enforces_user_isolation(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, _, _ = schedule_mcp

    with _mcp_user(201, client_id="client-a"):
        created = await _call_tool(mcp, "create_task", {"title": "User A secret"})
        task_id = created["task"]["task_id"]

    with _mcp_user(202, client_id="client-b"):
        listed = await _call_tool(mcp, "list_tasks", {"include_completed": True})
        assert listed["tasks"] == []

        upd = await _call_tool(
            mcp, "update_task", {"task_id": task_id, "title": "Hijacked"}
        )
        assert upd["success"] is False
        assert upd["errorCode"] == ErrorCode.NOT_FOUND

        dele = await _call_tool(mcp, "delete_task", {"task_id": task_id})
        assert dele["success"] is False
        assert dele["errorCode"] == ErrorCode.NOT_FOUND


async def test_schedule_mcp_records_event_provenance_and_task_syn(
    component_core: ServerCore,
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, _, event_log = schedule_mcp
    schedule_events: list[ScheduleUpdatedEvent] = []

    async def _on_schedule_updated(ev: ScheduleUpdatedEvent) -> None:
        schedule_events.append(ev)

    component_core.event_bus.subscribe(
        ScheduleUpdatedEvent, _on_schedule_updated, inline=True
    )

    with _mcp_user(301, client_id="magic-todo"):
        created = await _call_tool(
            mcp,
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

        await _call_tool(
            mcp,
            "update_task",
            {
                "task_id": task_id,
                "status": "completed",
                "cause_seq": "9002",
                "reason": "Crossed off on page 2",
            },
        )
        await _call_tool(
            mcp,
            "delete_task",
            {
                "task_id": task_id,
                "cause_seq": "9003",
                "reason": "Duplicate task pruned",
            },
        )

    assert len(schedule_events) == 3
    assert all(ev.user_id == 301 and ev.task_id == task_id for ev in schedule_events)

    page = await event_log.list_events(user_id=301)
    assert [e.event_type for e in page.events] == [
        DomainEventType.SCHEDULE_TASK_CREATED,
        DomainEventType.SCHEDULE_TASK_UPDATED,
        DomainEventType.SCHEDULE_TASK_DELETED,
    ]
    assert all(e.actor == "oauth:magic-todo" for e in page.events)
    assert all(e.related_file_id == 5555 for e in page.events)
    assert page.events[0].payload["cause_seq"] == "9001"
    assert page.events[0].payload["reason"] == "Extracted from handwritten bullet"
    assert page.events[1].payload["cause_seq"] == "9002"
    assert page.events[1].payload["reason"] == "Crossed off on page 2"
    assert page.events[2].payload["cause_seq"] == "9003"
    assert page.events[2].payload["reason"] == "Duplicate task pruned"


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
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
    args: dict[str, Any],
    expected_code: ErrorCode,
) -> None:
    mcp, _, _ = schedule_mcp
    with _mcp_user(401):
        resp = await _call_tool(mcp, "create_task", args)
    assert resp["success"] is False
    assert resp["errorCode"] == expected_code


async def test_create_task_normalizes_zero_due_time(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, _, _ = schedule_mcp
    with _mcp_user(402):
        created = await _call_tool(
            mcp, "create_task", {"title": "Valid", "due_time": 0}
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
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
    update_args: dict[str, Any],
) -> None:
    mcp, _, _ = schedule_mcp
    with _mcp_user(403):
        created = await _call_tool(mcp, "create_task", {"title": "Valid"})
        resp = await _call_tool(
            mcp,
            "update_task",
            {"task_id": created["task"]["task_id"], **update_args},
        )
    assert resp["success"] is False
    assert resp["errorCode"] == ErrorCode.BAD_REQUEST


async def test_schedule_mcp_bounds_provenance_and_uses_token_actor(
    schedule_mcp: tuple[MCPServer, ScheduleService, EventLogService],
) -> None:
    mcp, _, event_log = schedule_mcp
    with _mcp_user(501, client_id="api_key", actor="api_key:42"):
        created = await _call_tool(
            mcp,
            "create_task",
            {
                "title": "Bounded provenance task",
                "cause_seq": "1" * 100,
                "reason": "r" * 800,
            },
        )
        assert created["success"] is True

    page = await event_log.list_events(user_id=501)
    assert len(page.events) == 1
    assert page.events[0].actor == "api_key:42"
    assert len(page.events[0].payload["cause_seq"]) == 64
    assert len(page.events[0].payload["reason"]) == 500
