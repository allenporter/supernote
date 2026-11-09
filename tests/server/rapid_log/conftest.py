"""Shared `MagicTodoSimulator` timeline test harness and fixtures for `supernote.server.rapid_log`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

import pytest

from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.rapid_log import (
    MAX_TASK_DETAIL_LENGTH,
    MAX_TASK_TITLE_LENGTH,
    NotebookPageInput,
    ReconciliationPlan,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    plan_notebook_deletion,
    reconcile_rapid_log,
)


def utc_ms(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    """Return UTC epoch milliseconds."""
    return int(
        datetime(
            year, month, day, hour, minute, second, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )


def make_page_id(
    year: int,
    month: int,
    day: int,
    hour: int = 9,
    minute: int = 0,
    second: int = 0,
    suffix: str = "abc123",
) -> str:
    """Build a realistic Supernote `P<YYYYMMDDHHMMSS><suffix>` page ID."""
    return f"P{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}{second:02d}{suffix}"


@dataclass
class SimulatedPage:
    page_id: str
    text: str
    modified_ms: int


@dataclass
class SimulatedNotebook:
    file_id: int
    file_path: str
    pages: list[SimulatedPage] = field(default_factory=list)


class MagicTodoSimulator:
    """Queue-independent, deterministic timeline simulator for Magic To-Do reconciliation.

    Automatically enforces core invariants on every `sync_notebook` step:
    - Disjoint task action IDs (`create_tasks`, `update_tasks`, `delete_tasks` never overlap).
    - Strict title/detail length limits and valid 1-indexed `ScheduleTaskLinkDTO` Base64 links.
    - Strict idempotency: an immediate second reconciliation at the same timestamp produces
      zero task mutations and identical entry state.
    """

    def __init__(self, start_time_ms: int = utc_ms(2026, 10, 26, 9, 0, 0)) -> None:
        self.clock_ms = start_time_ms
        self._task_seq = 0
        self.notebooks: dict[int, SimulatedNotebook] = {}
        self.entries_by_file: dict[int, list[SyncedRapidLogEntry]] = {}
        self.tasks: dict[str, RemoteTaskSnapshot] = {}

    def advance(
        self, *, seconds: int = 0, minutes: int = 0, hours: int = 0, days: int = 0
    ) -> int:
        delta_ms = (((days * 24 + hours) * 60 + minutes) * 60 + seconds) * 1000
        self.clock_ms += delta_ms
        return self.clock_ms

    def _next_task_id(self) -> str:
        self._task_seq += 1
        return f"task-{self._task_seq}"

    def create_notebook(self, file_id: int, file_path: str) -> SimulatedNotebook:
        nb = SimulatedNotebook(file_id=file_id, file_path=file_path)
        self.notebooks[file_id] = nb
        return nb

    def set_page(
        self,
        file_id: int,
        page_id: str,
        text: str,
        *,
        insert_at: int | None = None,
        modified_ms: int | None = None,
    ) -> None:
        nb = self.notebooks[file_id]
        mod_ms = modified_ms if modified_ms is not None else self.clock_ms
        for p in nb.pages:
            if p.page_id == page_id:
                p.text = text
                p.modified_ms = mod_ms
                return
        new_page = SimulatedPage(page_id=page_id, text=text, modified_ms=mod_ms)
        if insert_at is None:
            nb.pages.append(new_page)
        else:
            nb.pages.insert(insert_at, new_page)

    def remove_page(self, file_id: int, page_id: str) -> None:
        nb = self.notebooks[file_id]
        nb.pages = [p for p in nb.pages if p.page_id != page_id]

    def rename_notebook(self, file_id: int, new_path: str) -> None:
        self.notebooks[file_id].file_path = new_path

    def digital_complete(self, task_id: str, *, at_ms: int | None = None) -> None:
        ts = at_ms if at_ms is not None else self.clock_ms
        t = self.tasks[task_id]
        self.tasks[task_id] = replace(
            t, status="completed", completed_time=ts, update_time=ts
        )

    def digital_reopen(self, task_id: str, *, at_ms: int | None = None) -> None:
        ts = at_ms if at_ms is not None else self.clock_ms
        t = self.tasks[task_id]
        self.tasks[task_id] = replace(
            t, status="needsAction", completed_time=0, update_time=ts
        )

    def digital_edit(
        self,
        task_id: str,
        *,
        at_ms: int | None = None,
        title: str | None = None,
        detail: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        task_list_id: str | None = None,
    ) -> None:
        ts = at_ms if at_ms is not None else self.clock_ms
        t = self.tasks[task_id]
        self.tasks[task_id] = replace(
            t,
            title=t.title if title is None else title,
            detail=t.detail if detail is None else detail,
            importance=t.importance if importance is None else importance,
            due_time=t.due_time if due_time is None else due_time,
            task_list_id=t.task_list_id if task_list_id is None else task_list_id,
            update_time=ts,
        )

    def digital_delete(self, task_id: str) -> None:
        self.tasks.pop(task_id, None)

    def sync_notebook(
        self,
        file_id: int,
        *,
        sync_time_ms: int | None = None,
        include_external_notebooks: bool = True,
    ) -> ReconciliationPlan:
        ts = sync_time_ms if sync_time_ms is not None else self.clock_ms
        nb = self.notebooks[file_id]
        page_inputs = [
            NotebookPageInput(
                page_id=p.page_id,
                page_index=idx,
                text_content=p.text,
                page_modified_ms=p.modified_ms,
            )
            for idx, p in enumerate(nb.pages)
        ]
        prev_entries = self.entries_by_file.get(file_id, [])
        external_entries: list[SyncedRapidLogEntry] = []
        if include_external_notebooks:
            for other_fid, entries in self.entries_by_file.items():
                if other_fid != file_id:
                    external_entries.extend(entries)

        plan = reconcile_rapid_log(
            file_id=nb.file_id,
            file_path=nb.file_path,
            pages=page_inputs,
            prev_entries=prev_entries,
            remote_tasks=self.tasks,
            sync_time_ms=ts,
            external_entries=external_entries,
            task_id_factory=self._next_task_id,
        )

        # Invariant 1: Action IDs are strictly disjoint
        created_ids = {c.task_id for c in plan.create_tasks}
        updated_ids = {u.task_id for u in plan.update_tasks}
        deleted_ids = {d.task_id for d in plan.delete_tasks}
        assert len(created_ids) == len(plan.create_tasks)
        assert len(updated_ids) == len(plan.update_tasks)
        assert len(deleted_ids) == len(plan.delete_tasks)
        assert created_ids.isdisjoint(updated_ids)
        assert created_ids.isdisjoint(deleted_ids)
        assert updated_ids.isdisjoint(deleted_ids)

        for c in plan.create_tasks:
            assert 1 <= len(c.title) <= MAX_TASK_TITLE_LENGTH
            assert len(c.detail) <= MAX_TASK_DETAIL_LENGTH
            decoded_link = ScheduleTaskLinkDTO.from_b64(c.links)
            assert decoded_link.app_name == "Note"
            assert decoded_link.file_id == str(file_id)
            assert decoded_link.page >= 1
            self.tasks[c.task_id] = RemoteTaskSnapshot(
                task_id=c.task_id,
                title=c.title,
                detail=c.detail,
                status=c.status,
                importance=c.importance,
                due_time=c.due_time,
                completed_time=c.completed_time_ms,
                links=c.links,
                task_list_id="group-from-notes",
                update_time=c.last_modified_ms,
            )

        for u in plan.update_tasks:
            existing = self.tasks[u.task_id]
            merged = replace(
                existing,
                title=u.updates.get("title", existing.title),
                detail=u.updates.get("detail", existing.detail),
                status=u.updates.get("status", existing.status),
                importance=u.updates.get("importance", existing.importance),
                due_time=u.updates.get("due_time", existing.due_time),
                completed_time=u.updates.get("completed_time", existing.completed_time),
                links=u.updates.get("links", existing.links),
                update_time=u.updates["update_time"],
            )
            assert 1 <= len(merged.title) <= MAX_TASK_TITLE_LENGTH
            assert len(merged.detail or "") <= MAX_TASK_DETAIL_LENGTH
            if merged.links:
                decoded = ScheduleTaskLinkDTO.from_b64(merged.links)
                assert decoded.page >= 1
            self.tasks[u.task_id] = merged

        for d in plan.delete_tasks:
            self.tasks.pop(d.task_id, None)

        self.entries_by_file[file_id] = list(plan.entries)
        if plan.updated_external_entries:
            for ext_upd in plan.updated_external_entries:
                ext_list = self.entries_by_file.get(ext_upd.file_id, [])
                for i, old_e in enumerate(ext_list):
                    if (
                        old_e.page_id == ext_upd.page_id
                        and old_e.item_order == ext_upd.item_order
                        and old_e.normalized_text == ext_upd.normalized_text
                    ):
                        ext_list[i] = ext_upd
                        break

        # Invariant 2: Strict immediate idempotency!
        post_external: list[SyncedRapidLogEntry] = []
        if include_external_notebooks:
            for other_fid, entries in self.entries_by_file.items():
                if other_fid != file_id:
                    post_external.extend(entries)

        recheck = reconcile_rapid_log(
            file_id=nb.file_id,
            file_path=nb.file_path,
            pages=page_inputs,
            prev_entries=self.entries_by_file[file_id],
            remote_tasks=self.tasks,
            sync_time_ms=ts,
            external_entries=post_external,
            task_id_factory=lambda: pytest.fail(
                "Idempotency violation: minted task_id on immediate re-sync"
            ),
        )
        assert not recheck.has_task_mutations, f"Non-idempotent recheck: {recheck}"
        assert recheck.updated_external_entries == []
        assert recheck.entries == self.entries_by_file[file_id]

        return plan

    def delete_notebook(self, file_id: int) -> list[str]:
        entries = self.entries_by_file.pop(file_id, [])
        self.notebooks.pop(file_id, None)
        deletions = plan_notebook_deletion(entries, self.tasks)
        deleted_ids: list[str] = []
        for d in deletions:
            self.tasks.pop(d.task_id, None)
            deleted_ids.append(d.task_id)
        return deleted_ids


@pytest.fixture
def simulator() -> MagicTodoSimulator:
    """Fresh `MagicTodoSimulator` starting Monday 2026-10-26 09:00 UTC."""
    return MagicTodoSimulator()
