"""Unit and live-server integration tests for `evals.magic_todo.agent`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient

from evals.magic_todo.agent import (
    CreateTaskAction,
    DeleteTaskAction,
    FileCursorStore,
    MagicTodoAgent,
    MemoryCursorStore,
    SyncResult,
    TaskAction,
    UpdateTaskAction,
)
from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.events import EventsClient
from supernote.client.exceptions import GoneException
from supernote.client.schedule import ScheduleClient
from supernote.models.events import (
    DomainEntityType,
    DomainEventType,
    DomainEventVO,
    EventFeedListVO,
)
from supernote.models.schedule import ScheduleTaskInfo, ScheduleTaskLinkDTO
from supernote.server.components.events.service import (
    EVENT_LOG_SERVICE_KEY,
    EventLogService,
    encode_sync_token,
)
from supernote.server.services.user import UserService


class _ScriptedReconciler:
    """Deterministic fake `TaskReconciler` for testing `MagicTodoAgent` without an LLM."""

    def __init__(
        self,
        handler: Callable[
            [Sequence[DomainEventVO], Sequence[ScheduleTaskInfo]], Sequence[TaskAction]
        ],
    ) -> None:
        self._handler = handler
        self.calls: list[tuple[list[DomainEventVO], list[ScheduleTaskInfo]]] = []

    async def reconcile(
        self,
        events: Sequence[DomainEventVO],
        existing_tasks: Sequence[ScheduleTaskInfo],
    ) -> Sequence[TaskAction]:
        self.calls.append((list(events), list(existing_tasks)))
        return self._handler(events, existing_tasks)


@dataclass
class _LiveAgentEnv:
    """Live HTTP client harness backed by an API-key authenticated user."""

    user_id: int
    event_log_service: EventLogService
    events_client: EventsClient
    schedule_client: ScheduleClient
    cursor_store: FileCursorStore


@pytest_asyncio.fixture
async def live_agent_env(
    client: TestClient,
    user_service: UserService,
    test_user_id: int,
    tmp_path: Path,
) -> _LiveAgentEnv:
    """Provision an API-key authenticated `EventsClient`, `ScheduleClient`, and `FileCursorStore`."""
    assert client.app is not None
    raw_key, _ = await user_service.create_api_key(test_user_id, "Magic Todo Agent")

    class _ApiKeyAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return raw_key

    http_client = Client(
        client.session, auth=_ApiKeyAuth(), host=str(client.make_url("/"))
    )
    return _LiveAgentEnv(
        user_id=test_user_id,
        event_log_service=client.app[EVENT_LOG_SERVICE_KEY],
        events_client=EventsClient(http_client),
        schedule_client=ScheduleClient(http_client),
        cursor_store=FileCursorStore(tmp_path / "magic_todo_cursor.json"),
    )


def test_file_cursor_store_roundtrip_and_corrupt_recovery(tmp_path: Path) -> None:
    """Verify FileCursorStore persists syncToken atomically and tolerates missing/corrupt files."""
    cursor_path = tmp_path / "state" / "cursor.json"
    store = FileCursorStore(cursor_path)

    assert store.load() is None

    store.save("djE6MTAw")
    assert store.load() == "djE6MTAw"

    store.save(None)
    assert store.load() is None

    cursor_path.write_text("{not valid json", encoding="utf-8")
    assert store.load() is None


async def test_magic_todo_agent_creates_deep_linked_task_and_suppresses_self_echo(
    live_agent_env: _LiveAgentEnv,
) -> None:
    """Verify sync_once creates a deep-linked task and suppresses its own echo on the next poll."""
    env = live_agent_env
    reconciler = _ScriptedReconciler(
        lambda events, _tasks: [
            CreateTaskAction(
                title="Buy coffee",
                detail="From Daily.note",
                link=ScheduleTaskLinkDTO(
                    app_name="Note",
                    path="/Note/Daily.note",
                    page=int(ev.payload.get("page_index", 0)) + 1,
                    file_id=str(ev.payload["file_id"]),
                    page_id=str(ev.payload["page_id"]),
                ),
            )
            for ev in events
            if ev.event_type == DomainEventType.NOTE_PAGE_TRANSCRIBED
        ]
    )
    agent = MagicTodoAgent(
        events_client=env.events_client,
        schedule_client=env.schedule_client,
        reconciler=reconciler,
        cursor_store=env.cursor_store,
    )

    await env.event_log_service.append(
        user_id=env.user_id,
        event_type=DomainEventType.NOTE_PAGE_TRANSCRIBED,
        entity_type=DomainEntityType.NOTE_PAGE,
        entity_id="9001:P1",
        related_file_id=9001,
        actor="system:processor",
        payload={
            "file_id": "9001",
            "file_path": "NOTE/Note/Daily.note",
            "page_id": "P1",
            "page_index": 0,
            "text_content": "• Buy coffee",
            "previous_text": None,
        },
    )

    res1 = await agent.sync_once()
    assert res1.events_processed == 1
    assert res1.actions_applied == 1
    assert res1.cursor_reset is False
    assert env.cursor_store.load() == res1.next_sync_token

    tasks = [t async for t in env.schedule_client.list_tasks()]
    assert len(tasks) == 1
    assert tasks[0].title == "Buy coffee"
    assert tasks[0].links is not None
    decoded_link = ScheduleTaskLinkDTO.from_b64(tasks[0].links)
    assert decoded_link.file_id == "9001"
    assert decoded_link.page_id == "P1"

    res2 = await agent.sync_once()
    assert res2.events_processed == 0
    assert res2.actions_applied == 0
    assert len(reconciler.calls) == 1


async def test_magic_todo_agent_updates_preserves_completed_time_clears_link_and_deletes(
    live_agent_env: _LiveAgentEnv,
) -> None:
    """Verify UpdateTaskAction preserves existing completed_time, clears completed_time/links, and DeleteTaskAction removes tasks."""
    env = live_agent_env
    created = await env.schedule_client.create_task(
        group_id=None,
        title="Buy coffee",
        links=ScheduleTaskLinkDTO(
            app_name="Note",
            path="/Note/Daily.note",
            page=1,
            file_id="9001",
            page_id="P1",
        ).to_b64(),
    )
    assert created.task_id is not None

    planned_actions: list[TaskAction] = [
        UpdateTaskAction(task_id=created.task_id, status="completed")
    ]
    agent = MagicTodoAgent(
        events_client=env.events_client,
        schedule_client=env.schedule_client,
        reconciler=_ScriptedReconciler(lambda _e, _t: list(planned_actions)),
        cursor_store=env.cursor_store,
    )

    async def _emit_page_event(seq_tag: str) -> None:
        await env.event_log_service.append(
            user_id=env.user_id,
            event_type=DomainEventType.NOTE_PAGE_TRANSCRIBED,
            entity_type=DomainEntityType.NOTE_PAGE,
            entity_id=f"9001:{seq_tag}",
            related_file_id=9001,
            actor="system:processor",
            payload={"file_id": "9001", "page_id": seq_tag, "text_content": seq_tag},
        )

    await _emit_page_event("P1")
    await agent.sync_once()
    first_completed = [t async for t in env.schedule_client.list_tasks()][0]
    assert first_completed.status == "completed"
    assert (first_completed.completed_time or 0) > 0

    # Re-sending status="completed" preserves the existing completed_time timestamp
    await _emit_page_event("P1b")
    await agent.sync_once()
    second_completed = [t async for t in env.schedule_client.list_tasks()][0]
    assert second_completed.completed_time == first_completed.completed_time

    # Reopening and clearing deep-link resets completed_time and links
    planned_actions[:] = [
        UpdateTaskAction(task_id=created.task_id, status="needsAction", clear_link=True)
    ]
    await _emit_page_event("P1c")
    await agent.sync_once()
    reopened = [t async for t in env.schedule_client.list_tasks()][0]
    assert reopened.status == "needsAction"
    assert (reopened.completed_time or 0) == 0
    assert reopened.links is None

    # Deleting via DeleteTaskAction removes the task
    planned_actions[:] = [DeleteTaskAction(task_id=created.task_id)]
    await env.event_log_service.append(
        user_id=env.user_id,
        event_type=DomainEventType.NOTE_PAGES_DELTA,
        entity_type=DomainEntityType.FILE,
        entity_id="9001",
        related_file_id=9001,
        actor="system:processor",
        payload={"file_id": "9001", "deleted_pages": ["P1"]},
    )
    await agent.sync_once()
    assert [t async for t in env.schedule_client.list_tasks()] == []


async def test_magic_todo_agent_recovers_from_http_410_expired_cursor(
    live_agent_env: _LiveAgentEnv,
) -> None:
    """Verify HTTP 410 Gone resets the expired cursor and resumes cleanly."""
    env = live_agent_env
    old_ev = await env.event_log_service.append(
        user_id=env.user_id,
        event_type=DomainEventType.FILE_DELETED,
        entity_type=DomainEntityType.FILE,
        entity_id="9999",
        actor="user:web",
        timestamp_ms=1_000,
    )
    await env.event_log_service.prune_expired_events(max_age_ms=1_000)
    env.cursor_store.save(encode_sync_token(old_ev.seq - 1))

    agent = MagicTodoAgent(
        events_client=env.events_client,
        schedule_client=env.schedule_client,
        reconciler=_ScriptedReconciler(lambda _e, _t: []),
        cursor_store=env.cursor_store,
    )
    res = await agent.sync_once()
    assert res.cursor_reset is True
    assert env.cursor_store.load() == res.next_sync_token


async def test_magic_todo_agent_skips_non_actionable_delta_and_paginates() -> None:
    """Verify note.pages_delta without deletions skips reconcile and multi-page feeds drain fully."""
    events_client = AsyncMock(spec=EventsClient)
    schedule_client = AsyncMock(spec=ScheduleClient)

    async def _empty_tasks():
        if False:
            yield ScheduleTaskInfo()

    schedule_client.list_tasks.side_effect = lambda: _empty_tasks()

    non_actionable = DomainEventVO(
        seq="1",
        timestamp=1_700_000_000_000,
        event_type=DomainEventType.NOTE_PAGES_DELTA,
        actor="system:processor",
        entity_type=DomainEntityType.FILE,
        entity_id="1",
        payload={"added_pages": ["P1"], "deleted_pages": []},
    )
    events_client.list_events.side_effect = [
        EventFeedListVO(
            events=[non_actionable], next_sync_token="djE6MQ", has_more=True
        ),
        EventFeedListVO(events=[], next_sync_token="djE6Mg", has_more=False),
    ]

    reconciler = _ScriptedReconciler(lambda _e, _t: [CreateTaskAction(title="Unused")])
    store = MemoryCursorStore()
    agent = MagicTodoAgent(
        events_client=events_client,
        schedule_client=schedule_client,
        reconciler=reconciler,
        cursor_store=store,
    )
    res = await agent.sync_once()
    assert res == SyncResult(
        events_processed=0,
        actions_applied=0,
        cursor_reset=False,
        next_sync_token="djE6Mg",
    )
    assert reconciler.calls == []
    assert store.load() == "djE6Mg"


async def test_magic_todo_agent_dry_run_never_mutates_tasks_or_cursor_even_on_410() -> (
    None
):
    """Verify dry_run=True skips schedule mutations and leaves cursor_store untouched, including on HTTP 410."""
    events_client = AsyncMock(spec=EventsClient)
    schedule_client = AsyncMock(spec=ScheduleClient)

    async def _empty_tasks():
        if False:
            yield ScheduleTaskInfo()

    schedule_client.list_tasks.side_effect = lambda: _empty_tasks()
    ev = DomainEventVO(
        seq="10",
        timestamp=1_700_000_000_000,
        event_type=DomainEventType.NOTE_PAGE_TRANSCRIBED,
        actor="system:processor",
        entity_type=DomainEntityType.NOTE_PAGE,
        entity_id="1:P1",
        payload={"text_content": "• Dry run task"},
    )
    events_client.list_events.side_effect = [
        GoneException("Cursor expired"),
        EventFeedListVO(events=[ev], next_sync_token="djE6MTA", has_more=False),
    ]

    store = MemoryCursorStore("djE6MQ")
    agent = MagicTodoAgent(
        events_client=events_client,
        schedule_client=schedule_client,
        reconciler=_ScriptedReconciler(lambda _e, _t: [CreateTaskAction(title="Dry")]),
        cursor_store=store,
        dry_run=True,
    )
    res = await agent.sync_once()
    assert res == SyncResult(
        events_processed=1,
        actions_applied=1,
        cursor_reset=True,
        next_sync_token="djE6MTA",
    )
    schedule_client.create_task.assert_not_awaited()
    assert store.load() == "djE6MQ"


async def test_magic_todo_agent_preserves_cursor_when_action_apply_fails() -> None:
    """Verify a mid-batch ScheduleClient failure leaves the persisted cursor unchanged for replay."""
    events_client = AsyncMock(spec=EventsClient)
    schedule_client = AsyncMock(spec=ScheduleClient)

    async def _empty_tasks():
        if False:
            yield ScheduleTaskInfo()

    schedule_client.list_tasks.side_effect = lambda: _empty_tasks()
    schedule_client.create_task.side_effect = [None, RuntimeError("Network error")]
    ev = DomainEventVO(
        seq="10",
        timestamp=1_700_000_000_000,
        event_type=DomainEventType.NOTE_PAGE_TRANSCRIBED,
        actor="system:processor",
        entity_type=DomainEntityType.NOTE_PAGE,
        entity_id="1:P1",
        payload={"text_content": "• Task 1\n• Task 2"},
    )
    events_client.list_events.return_value = EventFeedListVO(
        events=[ev], next_sync_token="djE6MTA", has_more=False
    )

    store = MemoryCursorStore("djE6MQ")
    agent = MagicTodoAgent(
        events_client=events_client,
        schedule_client=schedule_client,
        reconciler=_ScriptedReconciler(
            lambda _e, _t: [
                CreateTaskAction(title="Task 1"),
                CreateTaskAction(title="Task 2"),
            ]
        ),
        cursor_store=store,
    )
    with pytest.raises(RuntimeError, match="Network error"):
        await agent.sync_once()
    assert store.load() == "djE6MQ"
