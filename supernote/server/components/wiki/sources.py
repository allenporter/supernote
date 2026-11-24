"""Source-context loading and provenance invalidation helpers for the wiki compiler."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select, update

from supernote.models.events import DomainEventType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.models.wiki import WikiSourceRefDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded

__all__ = [
    "load_linked_context",
    "mark_deleted_sources_from_events",
    "mark_file_sources_deleted",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


async def mark_file_sources_deleted(
    session_manager: DatabaseSessionManager,
    user_id: int,
    file_id: int,
) -> None:
    """Mark all wiki source refs citing `file_id` as deleted (idempotent)."""
    now = _now_ms()
    async with session_manager.session() as session:
        await session.execute(
            update(WikiSourceRefDO)
            .where(
                WikiSourceRefDO.user_id == user_id,
                WikiSourceRefDO.file_id == file_id,
            )
            .values(is_source_deleted=True, update_time=now)
        )
        await session.commit()


async def mark_deleted_sources_from_events(
    session_manager: DatabaseSessionManager,
    user_id: int,
    events: list[DomainEventRecorded],
) -> None:
    """Flag wiki source refs whose cited file, note page, or task was soft-deleted."""
    now = _now_ms()
    deleted_file_ids: set[int] = set()
    deleted_page_keys: set[str] = set()
    deleted_task_ids: set[str] = set()
    for ev in events:
        if ev.event_type == DomainEventType.FILE_DELETED.value and ev.related_file_id:
            deleted_file_ids.add(ev.related_file_id)
        elif (
            ev.event_type == DomainEventType.NOTE_PAGES_DELTA.value
            and ev.related_file_id
        ):
            for pid in ev.payload.get("deleted_pages") or []:
                deleted_page_keys.add(f"{ev.related_file_id}:{pid}")
        elif ev.event_type == DomainEventType.SCHEDULE_TASK_DELETED.value:
            deleted_task_ids.add(ev.entity_id)

    if not (deleted_file_ids or deleted_page_keys or deleted_task_ids):
        return
    async with session_manager.session() as session:
        if deleted_file_ids:
            await session.execute(
                update(WikiSourceRefDO)
                .where(
                    WikiSourceRefDO.user_id == user_id,
                    WikiSourceRefDO.file_id.in_(deleted_file_ids),
                )
                .values(is_source_deleted=True, update_time=now)
            )
        if deleted_page_keys:
            await session.execute(
                update(WikiSourceRefDO)
                .where(
                    WikiSourceRefDO.user_id == user_id,
                    WikiSourceRefDO.source_type == "note_page",
                    WikiSourceRefDO.source_key.in_(deleted_page_keys),
                )
                .values(is_source_deleted=True, update_time=now)
            )
        if deleted_task_ids:
            await session.execute(
                update(WikiSourceRefDO)
                .where(
                    WikiSourceRefDO.user_id == user_id,
                    WikiSourceRefDO.source_type == "schedule_task",
                    WikiSourceRefDO.source_key.in_(deleted_task_ids),
                )
                .values(is_source_deleted=True, update_time=now)
            )
        await session.commit()


async def load_linked_context(
    session_manager: DatabaseSessionManager,
    user_id: int,
    events: list[DomainEventRecorded],
) -> dict[str, Any]:
    """Load schedule task snapshots and linked notebook pages referenced by `events`."""
    task_ids = {ev.entity_id for ev in events if ev.entity_type == "schedule_task"}
    file_ids = {
        ev.related_file_id
        for ev in events
        if ev.related_file_id is not None and ev.entity_type == "schedule_task"
    }
    if not task_ids and not file_ids:
        return {}

    async with session_manager.session() as session:
        tasks_ctx: list[dict[str, Any]] = []
        if task_ids:
            rows = (
                (
                    await session.execute(
                        select(ScheduleTaskDO).where(
                            ScheduleTaskDO.user_id == user_id,
                            ScheduleTaskDO.task_id.in_(task_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            tasks_ctx = [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "detail": t.detail,
                    "status": t.status,
                    "importance": t.importance,
                    "recurrence": t.recurrence,
                    "due_time": t.due_time,
                    "completed_time": t.completed_time,
                }
                for t in rows
            ]

        pages_ctx: list[dict[str, Any]] = []
        if file_ids:
            # Strict tenant join: NotePageContentDO has no user_id column.
            page_rows = (
                (
                    await session.execute(
                        select(NotePageContentDO)
                        .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                        .where(
                            UserFileDO.user_id == user_id,
                            UserFileDO.is_active == "Y",
                            NotePageContentDO.file_id.in_(file_ids),
                            NotePageContentDO.text_content.is_not(None),
                        )
                        .limit(10)
                    )
                )
                .scalars()
                .all()
            )
            pages_ctx = [
                {
                    "file_id": p.file_id,
                    "page_id": p.page_id,
                    "page_index": p.page_index,
                    "text_content": (p.text_content or "")[:1500],
                }
                for p in page_rows
                if not p.is_blank
            ]
        return {"tasks": tasks_ctx, "linked_note_pages": pages_ctx}
