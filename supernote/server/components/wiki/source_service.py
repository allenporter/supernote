"""Internal read-only source-context service for the LLM Wiki compiler.

Isolates cross-table SQLite reads against source domains (`UserFileDO`,
`NotePageContentDO`, `ScheduleTaskDO`) behind one tenant-scoped internal
service so `WikiCompilerWorker` stays focused on orchestration and does not
import foreign ORM models directly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded

__all__ = ["WikiSourceService"]


class WikiSourceService:
    """Internal read adapter supplying notebook OCR and schedule snapshots to the compiler."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self._session_manager = session_manager

    async def load_linked_context(
        self, user_id: int, events: list[DomainEventRecorded]
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

        async with self._session_manager.session() as session:
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
                            .join(
                                UserFileDO, UserFileDO.id == NotePageContentDO.file_id
                            )
                            .where(
                                UserFileDO.user_id == user_id,
                                UserFileDO.is_active == "Y",
                                NotePageContentDO.file_id.in_(file_ids),
                                NotePageContentDO.text_content.is_not(None),
                            )
                            .order_by(
                                NotePageContentDO.file_id.desc(),
                                NotePageContentDO.page_index.asc(),
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

    async def list_backfill_batch(
        self,
        user_id: int,
        *,
        before_file_id: int | None,
        max_files: int = 5,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Load the next newest-first batch of `.note` OCR pages for wiki backfill.

        Returns `(synthetic_diffs, next_cursor_file_id)`. `next_cursor_file_id`
        is `None` when no more active `.note` files remain.
        """
        async with self._session_manager.session() as session:
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
                UserFileDO.is_folder == "N",
                UserFileDO.file_name.like("%.note"),
            )
            if before_file_id is not None:
                stmt = stmt.where(UserFileDO.id < before_file_id)
            files = (
                (
                    await session.execute(
                        stmt.order_by(UserFileDO.id.desc()).limit(
                            max(1, min(max_files, 20))
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not files:
                return [], None

            file_ids = [f.id for f in files]
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
                        .order_by(
                            NotePageContentDO.file_id.desc(),
                            NotePageContentDO.page_index.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )

        file_name_map = {f.id: f.file_name for f in files}
        synthetic_diffs = [
            {
                "event_type": "backfill.note_page",
                "entity_id": f"{p.file_id}:{p.page_id}",
                "related_file_id": p.file_id,
                "payload": {
                    "file_id": str(p.file_id),
                    "file_path": file_name_map.get(p.file_id, ""),
                    "page_id": p.page_id,
                    "page_index": p.page_index,
                    "text_content": p.text_content or "",
                },
            }
            for p in page_rows
            if not p.is_blank
        ]
        return synthetic_diffs, files[-1].id

    async def list_task_snapshots(
        self, user_id: int, *, limit: int = 50
    ) -> list[ScheduleTaskDO]:
        """Return up to `limit` schedule tasks for semantic lint drift checks."""
        async with self._session_manager.session() as session:
            return list(
                (
                    await session.execute(
                        select(ScheduleTaskDO)
                        .where(ScheduleTaskDO.user_id == user_id)
                        .order_by(ScheduleTaskDO.update_time.desc())
                        .limit(max(1, min(limit, 200)))
                    )
                )
                .scalars()
                .all()
            )
