"""Cursor-driven Magic Todo reconciliation agent (`MagicTodoAgent`).

Polls the per-user domain event feed (`EventsClient`) using a single persisted
`sync_token` cursor with `exclude_actors=["self"]` echo suppression, delegates
diff interpretation to a pluggable `TaskReconciler`, and applies resulting task
mutations (with `ScheduleTaskLinkDTO` page deep-links) via `ScheduleClient`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from supernote.client.events import EventsClient
from supernote.client.exceptions import GoneException
from supernote.client.schedule import ScheduleClient
from supernote.models.events import DomainEventType, DomainEventVO
from supernote.models.schedule import ScheduleTaskInfo, ScheduleTaskLinkDTO

__all__ = [
    "CreateTaskAction",
    "CursorStore",
    "DeleteTaskAction",
    "FileCursorStore",
    "MagicTodoAgent",
    "MemoryCursorStore",
    "SyncResult",
    "TaskAction",
    "TaskReconciler",
    "UpdateTaskAction",
]

logger = logging.getLogger(__name__)

DEFAULT_EVENT_TYPES: tuple[str, ...] = (
    DomainEventType.NOTE_PAGE_TRANSCRIBED,
    DomainEventType.NOTE_PAGES_DELTA,
    DomainEventType.VFS_DELETED,
    "schedule.*",
)


@dataclass(frozen=True)
class CreateTaskAction:
    """Instruction to create a new Supernote To-Do task."""

    title: str
    """Task title."""

    detail: str = ""
    """Optional task notes or detail text."""

    status: str = "needsAction"
    """Initial task status (`'needsAction'` or `'completed'`)."""

    importance: str | None = None
    """Optional importance level."""

    due_time: int | None = None
    """Optional due timestamp in UTC epoch milliseconds."""

    group_id: str | None = None
    """Optional target task group ID (falls back to agent's `default_group_id`)."""

    link: ScheduleTaskLinkDTO | None = None
    """Optional notebook/page deep-link metadata."""


@dataclass(frozen=True)
class UpdateTaskAction:
    """Instruction to partially update an existing Supernote To-Do task."""

    task_id: str
    """Identifier of the task to update."""

    title: str | None = None
    """Optional updated title."""

    detail: str | None = None
    """Optional updated detail text."""

    status: str | None = None
    """Optional updated status (`'needsAction'` or `'completed'`)."""

    importance: str | None = None
    """Optional updated importance level."""

    due_time: int | None = None
    """Optional updated due timestamp in UTC epoch milliseconds (`0` clears)."""

    group_id: str | None = None
    """Optional updated task group ID."""

    link: ScheduleTaskLinkDTO | None = None
    """Optional replacement notebook/page deep-link."""

    clear_link: bool = False
    """Remove any existing notebook/page deep-link when `True`."""


@dataclass(frozen=True)
class DeleteTaskAction:
    """Instruction to delete an existing Supernote To-Do task."""

    task_id: str
    """Identifier of the task to delete."""


type TaskAction = CreateTaskAction | UpdateTaskAction | DeleteTaskAction


class TaskReconciler(Protocol):
    """Pluggable reconciler mapping incremental domain events and tasks to actions."""

    async def reconcile(
        self,
        events: Sequence[DomainEventVO],
        existing_tasks: Sequence[ScheduleTaskInfo],
    ) -> Sequence[TaskAction]:
        """Compute task mutations for a chronological batch of domain events."""
        ...


class CursorStore(Protocol):
    """Persistence interface for storing a single opaque `sync_token` cursor."""

    def load(self) -> str | None:
        """Load the last persisted `sync_token`, or `None` if unset."""
        ...

    def save(self, sync_token: str | None) -> None:
        """Persist `sync_token` durably."""
        ...


class MemoryCursorStore:
    """In-memory `CursorStore` for tests and ephemeral agent runs."""

    def __init__(self, sync_token: str | None = None) -> None:
        self._sync_token = sync_token

    def load(self) -> str | None:
        """Return the current in-memory `sync_token`."""
        return self._sync_token

    def save(self, sync_token: str | None) -> None:
        """Store `sync_token` in memory."""
        self._sync_token = sync_token


class FileCursorStore:
    """Atomic JSON file-backed `CursorStore` persisting only `syncToken`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> str | None:
        """Load `syncToken` from the JSON cursor file, returning `None` if absent."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as err:
            logger.warning("Ignoring unreadable cursor file %s: %s", self._path, err)
            return None
        token = data.get("syncToken") if isinstance(data, dict) else None
        return token if isinstance(token, str) and token else None

    def save(self, sync_token: str | None) -> None:
        """Atomically write `syncToken` to the JSON cursor file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_name = tmp_file.name
                tmp_file.write(json.dumps({"syncToken": sync_token}, indent=2) + "\n")
            os.replace(tmp_name, self._path)
        except Exception:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            raise


@dataclass(frozen=True)
class SyncResult:
    """Summary of one `MagicTodoAgent.sync_once()` poll-and-reconcile cycle."""

    events_processed: int
    """Number of domain events passed to the reconciler."""

    actions_applied: int
    """Number of task mutations executed (or planned when `dry_run=True`)."""

    cursor_reset: bool
    """`True` if the server returned HTTP 410 Gone and the cursor was reset."""

    next_sync_token: str | None
    """Latest `sync_token` after this cycle (persisted unless `dry_run=True`)."""


def _is_actionable_event(event: DomainEventVO) -> bool:
    """Return `True` for domain events that can affect task state."""
    if event.event_type == DomainEventType.NOTE_PAGES_DELTA:
        return bool(event.payload.get("deleted_pages"))
    return True


class MagicTodoAgent:
    """Zero-shadow-state cursor agent synchronizing notebook diffs with Supernote To-Do."""

    def __init__(
        self,
        events_client: EventsClient,
        schedule_client: ScheduleClient,
        reconciler: TaskReconciler,
        *,
        cursor_store: CursorStore | None = None,
        default_group_id: str | None = None,
        exclude_actors: Sequence[str] | None = ("self",),
        event_types: Sequence[str] = DEFAULT_EVENT_TYPES,
        dry_run: bool = False,
    ) -> None:
        self._events_client = events_client
        self._schedule_client = schedule_client
        self._reconciler = reconciler
        self._cursor_store: CursorStore = (
            cursor_store if cursor_store is not None else MemoryCursorStore()
        )
        self._default_group_id = default_group_id
        self._exclude_actors = (
            list(exclude_actors) if exclude_actors is not None else None
        )
        self._event_types = list(event_types)
        self._dry_run = dry_run

    async def sync_once(self) -> SyncResult:
        """Drain new events since the saved cursor, reconcile tasks, and advance the cursor."""
        sync_token = self._cursor_store.load()
        cursor_reset = False
        try:
            events, next_token = await self._drain_events(sync_token)
        except GoneException:
            logger.warning(
                "Event cursor expired (HTTP 410); resetting cursor and resyncing."
            )
            cursor_reset = True
            events, next_token = await self._drain_events(None)

        actionable = [ev for ev in events if _is_actionable_event(ev)]
        actions_applied = 0
        if actionable:
            existing_tasks = [t async for t in self._schedule_client.list_tasks()]
            existing_by_id = {t.task_id: t for t in existing_tasks if t.task_id}
            actions = await self._reconciler.reconcile(actionable, existing_tasks)
            if not self._dry_run:
                for action in actions:
                    await self._apply_action(action, existing_by_id)
            actions_applied = len(actions)

        if not self._dry_run and (cursor_reset or next_token != sync_token):
            self._cursor_store.save(next_token)

        return SyncResult(
            events_processed=len(actionable),
            actions_applied=actions_applied,
            cursor_reset=cursor_reset,
            next_sync_token=next_token,
        )

    async def _drain_events(
        self, sync_token: str | None
    ) -> tuple[list[DomainEventVO], str | None]:
        """Page through all available events until `has_more` is `False`."""
        collected: list[DomainEventVO] = []
        cursor = sync_token
        while True:
            feed = await self._events_client.list_events(
                sync_token=cursor,
                event_types=self._event_types,
                exclude_actors=self._exclude_actors,
            )
            collected.extend(feed.events)
            cursor = feed.next_sync_token
            if not feed.has_more:
                return collected, cursor

    async def _apply_action(
        self,
        action: TaskAction,
        existing_by_id: dict[str, ScheduleTaskInfo],
    ) -> None:
        """Execute a single reconciled task mutation via `ScheduleClient`."""
        now_ms = int(time.time() * 1000)
        if isinstance(action, CreateTaskAction):
            completed_ms = now_ms if action.status == "completed" else None
            await self._schedule_client.create_task(
                group_id=(
                    action.group_id
                    if action.group_id is not None
                    else self._default_group_id
                ),
                title=action.title,
                detail=action.detail,
                status=action.status,
                importance=action.importance,
                due_time=action.due_time,
                completed_time_ms=completed_ms,
                links=action.link.to_b64() if action.link is not None else None,
            )
            return

        if isinstance(action, UpdateTaskAction):
            kwargs: dict[str, Any] = {}
            if action.title is not None:
                kwargs["title"] = action.title
            if action.detail is not None:
                kwargs["detail"] = action.detail
            if action.status is not None:
                kwargs["status"] = action.status
                if action.status == "completed":
                    existing = existing_by_id.get(action.task_id)
                    kwargs["completed_time_ms"] = (
                        existing.completed_time
                        if existing and existing.completed_time
                        else now_ms
                    )
                elif action.status == "needsAction":
                    kwargs["completed_time_ms"] = 0
            if action.importance is not None:
                kwargs["importance"] = action.importance
            if action.due_time is not None:
                kwargs["due_time"] = action.due_time
            if action.group_id is not None:
                kwargs["task_list_id"] = action.group_id
            if action.clear_link:
                kwargs["links"] = None
            elif action.link is not None:
                kwargs["links"] = action.link.to_b64()

            if kwargs:
                await self._schedule_client.update_task(action.task_id, **kwargs)
            return

        if isinstance(action, DeleteTaskAction):
            await self._schedule_client.delete_task(action.task_id)
