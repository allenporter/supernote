"""Internal read-only source-context service for the LLM Wiki compiler.

Isolates cross-table SQLite reads against source domains (`UserFileDO`,
`NotePageContentDO`, `ScheduleTaskDO`) behind one tenant-scoped internal
service so `WikiCompilerWorker` stays focused on orchestration and does not
import foreign ORM models directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, select

from supernote.models.wiki import WikiSourceRefDTO, WikiSourceType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded

__all__ = ["BackfillOverview", "SourceMetadata", "WikiSourceService"]


@dataclass(frozen=True)
class SourceMetadata:
    """Resolved human-readable display metadata for one wiki source reference."""

    file_name: str | None = None
    page_index: int | None = None
    task_title: str | None = None


@dataclass(frozen=True)
class BackfillOverview:
    """Snapshot of a user's notebook backfill progress and next batch preview."""

    remaining_files: int
    total_files: int
    untranscribed_files: int = 0
    next_files: list[str] = field(default_factory=list)


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

    def _transcribed_files_stmt(self, user_id: int) -> Select[UserFileDO]:
        """Return a tenant-scoped query for active files with at least one OCR'd page."""
        has_transcribed_page = (
            select(NotePageContentDO.id)
            .where(
                NotePageContentDO.file_id == UserFileDO.id,
                NotePageContentDO.text_content.is_not(None),
            )
            .correlate(UserFileDO)
            .exists()
        )
        return select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "N",
            has_transcribed_page,
        )

    def _untranscribed_note_files_stmt(self, user_id: int) -> Select[UserFileDO]:
        """Return a tenant-scoped query for active `.note` files without OCR text."""
        has_transcribed_page = (
            select(NotePageContentDO.id)
            .where(
                NotePageContentDO.file_id == UserFileDO.id,
                NotePageContentDO.text_content.is_not(None),
            )
            .correlate(UserFileDO)
            .exists()
        )
        return select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "N",
            func.lower(UserFileDO.file_name).like("%.note"),
            ~has_transcribed_page,
        )

    async def get_backfill_overview(
        self,
        user_id: int,
        *,
        before_file_id: int | None,
        preview_limit: int = 5,
    ) -> BackfillOverview:
        """Return backfill progress counts, un-OCR'd notebook count, and next filenames."""
        base_stmt = self._transcribed_files_stmt(user_id)
        remaining_stmt = (
            base_stmt
            if before_file_id is None
            else base_stmt.where(UserFileDO.id < before_file_id)
        )
        untranscribed_stmt = self._untranscribed_note_files_stmt(user_id)
        capped_preview = max(0, min(preview_limit, 20))

        async with self._session_manager.session() as session:
            total = int(
                (
                    await session.execute(
                        select(func.count()).select_from(base_stmt.subquery())
                    )
                ).scalar_one()
            )
            if before_file_id is None:
                remaining = total
            else:
                remaining = int(
                    (
                        await session.execute(
                            select(func.count()).select_from(remaining_stmt.subquery())
                        )
                    ).scalar_one()
                )
            untranscribed = int(
                (
                    await session.execute(
                        select(func.count()).select_from(untranscribed_stmt.subquery())
                    )
                ).scalar_one()
            )
            next_files: list[str] = []
            if remaining > 0 and capped_preview > 0:
                next_files = list(
                    (
                        await session.execute(
                            remaining_stmt.with_only_columns(UserFileDO.file_name)
                            .order_by(UserFileDO.id.desc())
                            .limit(capped_preview)
                        )
                    )
                    .scalars()
                    .all()
                )
        return BackfillOverview(
            remaining_files=remaining,
            total_files=total,
            untranscribed_files=untranscribed,
            next_files=next_files,
        )

    async def count_backfill_progress(
        self,
        user_id: int,
        *,
        before_file_id: int | None,
    ) -> tuple[int, int]:
        """Return `(remaining_files, total_files)` eligible for wiki backfill."""
        overview = await self.get_backfill_overview(
            user_id, before_file_id=before_file_id, preview_limit=0
        )
        return overview.remaining_files, overview.total_files

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
            stmt = self._transcribed_files_stmt(user_id)
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

    async def resolve_source_metadata(
        self, user_id: int, refs: Sequence[WikiSourceRefDTO]
    ) -> dict[tuple[WikiSourceType, str], SourceMetadata]:
        """Resolve display names and 0-based page indices for `refs` (tenant-scoped)."""
        if not refs:
            return {}

        file_ids: set[int] = set()
        note_pairs: list[tuple[int, str, str]] = []
        task_ids: set[str] = set()

        for ref in refs:
            if ref.source_type is WikiSourceType.NOTE_PAGE:
                fid = ref.file_id
                page_id = ""
                if ":" in ref.source_key:
                    raw_fid, page_id = ref.source_key.split(":", maxsplit=1)
                    if fid is None and raw_fid.isdigit():
                        fid = int(raw_fid)
                if fid is not None:
                    file_ids.add(fid)
                    note_pairs.append((fid, page_id, ref.source_key))
            elif ref.source_type is WikiSourceType.SCHEDULE_TASK:
                task_ids.add(ref.source_key)

        file_names: dict[int, str] = {}
        page_indices: dict[tuple[int, str], int] = {}
        task_titles: dict[str, str] = {}

        async with self._session_manager.session() as session:
            if file_ids:
                file_rows = (
                    await session.execute(
                        select(UserFileDO.id, UserFileDO.file_name).where(
                            UserFileDO.user_id == user_id,
                            UserFileDO.is_active == "Y",
                            UserFileDO.id.in_(file_ids),
                        )
                    )
                ).all()
                file_names = {int(fid): str(fname) for fid, fname in file_rows}

                page_rows = (
                    await session.execute(
                        select(
                            NotePageContentDO.file_id,
                            NotePageContentDO.page_id,
                            NotePageContentDO.page_index,
                        )
                        .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                        .where(
                            UserFileDO.user_id == user_id,
                            UserFileDO.is_active == "Y",
                            NotePageContentDO.file_id.in_(file_ids),
                        )
                    )
                ).all()
                page_indices = {
                    (int(fid), str(pid)): int(pidx)
                    for fid, pid, pidx in page_rows
                    if pid is not None
                }

            if task_ids:
                task_rows = (
                    await session.execute(
                        select(ScheduleTaskDO.task_id, ScheduleTaskDO.title).where(
                            ScheduleTaskDO.user_id == user_id,
                            ScheduleTaskDO.task_id.in_(task_ids),
                        )
                    )
                ).all()
                task_titles = {str(tid): str(title) for tid, title in task_rows}

        resolved: dict[tuple[WikiSourceType, str], SourceMetadata] = {}
        for fid, page_id, source_key in note_pairs:
            fname = file_names.get(fid)
            pidx = page_indices.get((fid, page_id)) if page_id else None
            if fname is not None or pidx is not None:
                resolved[(WikiSourceType.NOTE_PAGE, source_key)] = SourceMetadata(
                    file_name=fname,
                    page_index=pidx,
                )
        for tid in task_ids:
            if title := task_titles.get(tid):
                resolved[(WikiSourceType.SCHEDULE_TASK, tid)] = SourceMetadata(
                    task_title=title
                )
        return resolved

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
