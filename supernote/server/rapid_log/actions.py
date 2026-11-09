"""In-batch task action coalescing, no-op filtering, and visual creation ordering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from supernote.server.rapid_log.formatting import field_values_differ
from supernote.server.rapid_log.models import (
    CreateTaskAction,
    DeleteTaskAction,
    EntryLinkState,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    TaskStatus,
    UpdateTaskAction,
)

__all__ = [
    "ActionAccumulator",
]


class ActionAccumulator:
    """Coalesces task creates, updates, and deletes within a single reconciliation pass."""

    def __init__(
        self,
        remote_tasks: Mapping[str, RemoteTaskSnapshot],
        sync_time_ms: int,
        task_id_factory: Callable[[], str],
    ) -> None:
        self._orig_tasks = remote_tasks
        self.effective_tasks: dict[str, RemoteTaskSnapshot] = dict(remote_tasks)
        self._sync_time_ms = sync_time_ms
        self._task_id_factory = task_id_factory
        self._create_seq = 0
        self.pending_creates: dict[str, CreateTaskAction] = {}
        self.pending_updates: dict[str, dict[str, Any]] = {}
        self.pending_update_reasons: dict[str, str] = {}
        self.pending_deletes: dict[str, DeleteTaskAction] = {}

    def record_create(
        self,
        *,
        title: str,
        detail: str,
        importance: str,
        due_time: int | None,
        links: str,
        modified_ms: int,
    ) -> str:
        """Allocate a new task creation and register its effective snapshot."""
        task_id = self._task_id_factory()
        order_hint = self._create_seq
        self._create_seq += 1
        effective_modified = max(modified_ms, self._sync_time_ms) + order_hint
        self.pending_creates[task_id] = CreateTaskAction(
            task_id=task_id,
            title=title,
            detail=detail,
            status=TaskStatus.NEEDS_ACTION,
            importance=importance,
            due_time=due_time,
            completed_time_ms=None,
            links=links,
            last_modified_ms=effective_modified,
            order_hint=order_hint,
        )
        self.effective_tasks[task_id] = RemoteTaskSnapshot(
            task_id=task_id,
            title=title,
            detail=detail,
            status=TaskStatus.NEEDS_ACTION,
            importance=importance,
            due_time=due_time,
            completed_time=None,
            links=links,
            task_list_id=None,
            update_time=effective_modified,
        )
        return task_id

    def record_update(
        self,
        task_id: str,
        updates: Mapping[str, Any],
        *,
        reason: str,
        modified_ms: int,
    ) -> None:
        """Apply field updates, folding into a pending create when created in the same sync."""
        current = self.effective_tasks.get(task_id)
        if not updates or current is None:
            return
        actual_changes = {
            k: v
            for k, v in updates.items()
            if field_values_differ(k, getattr(current, k, None), v)
        }
        if not actual_changes:
            return

        new_update_time = max(modified_ms, self._sync_time_ms, current.update_time + 1)
        if task_id in self.pending_creates:
            created = self.pending_creates[task_id]
            self.pending_creates[task_id] = replace(
                created,
                title=actual_changes.get("title", created.title),
                detail=actual_changes.get("detail", created.detail),
                status=actual_changes.get("status", created.status),
                importance=actual_changes.get("importance", created.importance),
                due_time=actual_changes.get("due_time", created.due_time),
                completed_time_ms=actual_changes.get(
                    "completed_time", created.completed_time_ms
                ),
                links=actual_changes.get("links", created.links),
                last_modified_ms=new_update_time,
            )
        else:
            merged = self.pending_updates.setdefault(task_id, {})
            merged.update(actual_changes)
            merged["update_time"] = new_update_time
            self.pending_update_reasons[task_id] = reason

        self.effective_tasks[task_id] = replace(
            current,
            title=actual_changes.get("title", current.title),
            detail=actual_changes.get("detail", current.detail),
            status=actual_changes.get("status", current.status),
            importance=actual_changes.get("importance", current.importance),
            due_time=actual_changes.get("due_time", current.due_time),
            completed_time=actual_changes.get("completed_time", current.completed_time),
            links=actual_changes.get("links", current.links),
            update_time=new_update_time,
        )

    def record_delete(self, task_id: str, *, reason: str) -> None:
        """Delete a task, cancelling any pending create or update for the same `task_id`."""
        if task_id in self.pending_creates:
            self.pending_creates.pop(task_id, None)
            self.effective_tasks.pop(task_id, None)
            return
        self.pending_updates.pop(task_id, None)
        self.pending_update_reasons.pop(task_id, None)
        if task_id in self.effective_tasks:
            self.effective_tasks.pop(task_id, None)
            self.pending_deletes[task_id] = DeleteTaskAction(
                task_id=task_id, reason=reason
            )

    def finalize_actions(
        self, working_entries: Sequence[SyncedRapidLogEntry]
    ) -> tuple[list[CreateTaskAction], list[UpdateTaskAction], list[DeleteTaskAction]]:
        """Return disjoint `(create_tasks, update_tasks, delete_tasks)` with net no-ops stripped."""
        owner_order_by_task = {
            e.schedule_task_id: (e.page_index, e.page_id, e.item_order)
            for e in working_entries
            if e.link_state == EntryLinkState.ACTIVE and e.schedule_task_id is not None
        }
        sorted_creates = sorted(
            self.pending_creates.values(),
            key=lambda c: owner_order_by_task.get(c.task_id, (0, "", c.order_hint)),
        )
        create_actions = [
            replace(c, order_hint=idx) for idx, c in enumerate(sorted_creates)
        ]

        update_actions: list[UpdateTaskAction] = []
        for task_id, upd in self.pending_updates.items():
            orig = self._orig_tasks.get(task_id)
            if orig is None:
                continue
            net_changes = {
                k: v
                for k, v in upd.items()
                if k != "update_time"
                and field_values_differ(k, getattr(orig, k, None), v)
            }
            if not net_changes:
                continue
            net_changes["update_time"] = upd["update_time"]
            update_actions.append(
                UpdateTaskAction(
                    task_id=task_id,
                    updates=net_changes,
                    reason=self.pending_update_reasons[task_id],
                )
            )

        return create_actions, update_actions, list(self.pending_deletes.values())
