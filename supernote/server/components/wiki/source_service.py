"""Internal read-only source-context service for the LLM Wiki compiler.

Isolates cross-table SQLite reads against source domains (`UserFileDO`,
`NotePageContentDO`, `ScheduleTaskDO`) behind one tenant-scoped internal
service so `WikiCompilerWorker` stays focused on orchestration and does not
import foreign ORM models directly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.wiki import (
    WikiNotebookCoverageDTO,
    WikiSourceRefDTO,
    WikiSourceType,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.models.wiki import WikiPageDO, WikiSourceRefDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded

__all__ = [
    "BackfillOverview",
    "SourceMetadata",
    "WikiSourceService",
    "extract_page_timestamp_ms",
    "format_page_date",
]

_PAGE_ID_TS_RE = re.compile(r"^P(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def extract_page_timestamp_ms(page_id: str, fallback_ms: int) -> int:
    """Parse UTC epoch milliseconds from a Supernote `PYYYYMMDDHHMMSS...` page_id."""
    match = _PAGE_ID_TS_RE.match(page_id.strip())
    if match is not None:
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        if year >= 1970:
            try:
                dt = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
    return max(0, int(fallback_ms))


def format_page_date(ts_ms: int) -> str:
    """Format UTC epoch milliseconds as an ISO-8601 `YYYY-MM-DD` date string."""
    return datetime.fromtimestamp(max(0, ts_ms) / 1000, tz=UTC).strftime("%Y-%m-%d")


def _encode_page_cursor(ts_ms: int, file_id: int, page_index: int, row_id: int) -> str:
    """Build a fixed-width lexicographic cursor for global chronological page order."""
    return f"{max(0, ts_ms):016d}:{max(0, file_id):020d}:{max(0, page_index):08d}:{max(0, row_id):020d}"


@dataclass(frozen=True)
class _OrderedPageEntry:
    cursor: str
    row_id: int
    file_id: int
    file_name: str
    page_id: str
    page_index: int
    page_ts_ms: int


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
    remaining_pages: int = 0
    total_pages: int = 0
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

    async def _list_ordered_non_blank_pages(
        self, session: AsyncSession, user_id: int
    ) -> list[_OrderedPageEntry]:
        """Return all active non-blank OCR pages sorted chronologically by `page_date`."""
        rows = (
            await session.execute(
                select(
                    NotePageContentDO.id,
                    NotePageContentDO.file_id,
                    UserFileDO.file_name,
                    NotePageContentDO.page_id,
                    NotePageContentDO.page_index,
                    UserFileDO.update_time,
                    UserFileDO.create_time,
                )
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "N",
                    NotePageContentDO.text_content.is_not(None),
                    func.length(func.trim(NotePageContentDO.text_content, " \t\n\r"))
                    > 0,
                )
            )
        ).all()
        entries: list[_OrderedPageEntry] = []
        for row_id, file_id, file_name, page_id, page_index, update_t, create_t in rows:
            fallback_ms = int(update_t or create_t or 0)
            ts_ms = extract_page_timestamp_ms(page_id or "", fallback_ms)
            entries.append(
                _OrderedPageEntry(
                    cursor=_encode_page_cursor(
                        ts_ms, int(file_id), int(page_index), int(row_id)
                    ),
                    row_id=int(row_id),
                    file_id=int(file_id),
                    file_name=str(file_name or ""),
                    page_id=str(page_id or ""),
                    page_index=int(page_index),
                    page_ts_ms=ts_ms,
                )
            )
        entries.sort(key=lambda e: e.cursor)
        return entries

    async def get_backfill_overview(
        self,
        user_id: int,
        *,
        after_page_cursor: str | None = None,
        preview_limit: int = 5,
    ) -> BackfillOverview:
        """Return backfill progress counts, un-OCR'd notebook count, and next filenames."""
        untranscribed_stmt = self._untranscribed_note_files_stmt(user_id)
        capped_preview = max(0, min(preview_limit, 20))

        async with self._session_manager.session() as session:
            untranscribed = int(
                (
                    await session.execute(
                        select(func.count()).select_from(untranscribed_stmt.subquery())
                    )
                ).scalar_one()
            )
            entries = await self._list_ordered_non_blank_pages(session, user_id)
            total_pages = len(entries)
            total_files = len({e.file_id for e in entries})
            remaining_entries = (
                entries
                if after_page_cursor is None
                else [e for e in entries if e.cursor > after_page_cursor]
            )
            remaining_pages = len(remaining_entries)
            remaining_files = len({e.file_id for e in remaining_entries})
            next_files = (
                list(dict.fromkeys(e.file_name for e in remaining_entries))[
                    :capped_preview
                ]
                if capped_preview > 0
                else []
            )
        return BackfillOverview(
            remaining_files=remaining_files,
            total_files=total_files,
            remaining_pages=remaining_pages,
            total_pages=total_pages,
            untranscribed_files=untranscribed,
            next_files=next_files,
        )

    async def count_backfill_progress(
        self,
        user_id: int,
        *,
        after_page_cursor: str | None = None,
    ) -> tuple[int, int]:
        """Return `(remaining_files, total_files)` eligible for wiki backfill."""
        overview = await self.get_backfill_overview(
            user_id,
            after_page_cursor=after_page_cursor,
            preview_limit=0,
        )
        return overview.remaining_files, overview.total_files

    async def _build_page_window_diffs(
        self,
        session: AsyncSession,
        user_id: int,
        window: Sequence[_OrderedPageEntry],
    ) -> list[dict[str, Any]]:
        """Hydrate OCR text and build canonical compile diff dicts for `window`."""
        if not window:
            return []
        row_ids = [e.row_id for e in window]
        # Strict tenant join: NotePageContentDO has no user_id column.
        text_rows = (
            await session.execute(
                select(NotePageContentDO.id, NotePageContentDO.text_content)
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                    NotePageContentDO.id.in_(row_ids),
                )
            )
        ).all()
        text_by_id = {int(rid): str(txt or "") for rid, txt in text_rows}
        return [
            {
                "event_type": "backfill.note_page",
                "entity_id": f"{e.file_id}:{e.page_id}",
                "related_file_id": e.file_id,
                "payload": {
                    "file_id": str(e.file_id),
                    "file_path": e.file_name,
                    "page_id": e.page_id,
                    "page_index": e.page_index,
                    "page_date": format_page_date(e.page_ts_ms),
                    "text_content": text_by_id.get(e.row_id, ""),
                },
            }
            for e in window
        ]

    async def list_backfill_page_window(
        self,
        user_id: int,
        *,
        after_page_cursor: str | None,
        max_pages: int = 8,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Load the next chronological window of non-blank OCR pages across all notebooks.

        Returns `(synthetic_diffs, next_page_cursor)`. `next_page_cursor` is `None`
        when no more non-blank OCR pages remain.
        """
        capped_pages = max(1, min(max_pages, 50))
        async with self._session_manager.session() as session:
            entries = await self._list_ordered_non_blank_pages(session, user_id)
            remaining = (
                entries
                if after_page_cursor is None
                else [e for e in entries if e.cursor > after_page_cursor]
            )
            window = remaining[:capped_pages]
            if not window:
                return [], None
            synthetic_diffs = await self._build_page_window_diffs(
                session, user_id, window
            )
        return synthetic_diffs, window[-1].cursor

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

    async def get_notebook_coverage(
        self, user_id: int
    ) -> list[WikiNotebookCoverageDTO]:
        """Return per-notebook OCR vs. wiki citation coverage sorted lowest-coverage first."""
        async with self._session_manager.session() as session:
            page_stats = (
                await session.execute(
                    select(
                        UserFileDO.id,
                        UserFileDO.file_name,
                        func.count(NotePageContentDO.id),
                        func.avg(func.length(NotePageContentDO.text_content)),
                    )
                    .join(NotePageContentDO, NotePageContentDO.file_id == UserFileDO.id)
                    .where(
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                        UserFileDO.is_folder == "N",
                        NotePageContentDO.text_content.is_not(None),
                        func.length(
                            func.trim(NotePageContentDO.text_content, " \t\n\r")
                        )
                        > 0,
                    )
                    .group_by(UserFileDO.id, UserFileDO.file_name)
                )
            ).all()
            if not page_stats:
                return []

            ref_rows = (
                await session.execute(
                    select(
                        WikiSourceRefDO.file_id,
                        WikiSourceRefDO.source_key,
                        WikiPageDO.slug,
                    )
                    .join(
                        WikiPageDO,
                        (WikiPageDO.user_id == WikiSourceRefDO.user_id)
                        & (WikiPageDO.page_id == WikiSourceRefDO.page_id),
                    )
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.source_type == WikiSourceType.NOTE_PAGE.value,
                        WikiSourceRefDO.is_source_deleted.is_(False),
                        WikiPageDO.is_deleted.is_(False),
                    )
                )
            ).all()

        cited_keys_by_file: dict[int, set[str]] = {}
        cited_slugs_by_file: dict[int, set[str]] = {}
        for fid, source_key, slug in ref_rows:
            resolved_fid = fid
            if resolved_fid is None and ":" in (source_key or ""):
                prefix = source_key.split(":", maxsplit=1)[0]
                if prefix.isdigit():
                    resolved_fid = int(prefix)
            if resolved_fid is None:
                continue
            cited_keys_by_file.setdefault(int(resolved_fid), set()).add(str(source_key))
            cited_slugs_by_file.setdefault(int(resolved_fid), set()).add(str(slug))

        coverage: list[WikiNotebookCoverageDTO] = []
        for fid, fname, ocr_count, avg_len in page_stats:
            int_fid = int(fid)
            ocr_pages = int(ocr_count)
            cited_pages = min(ocr_pages, len(cited_keys_by_file.get(int_fid, ())))
            cited_slugs = sorted(cited_slugs_by_file.get(int_fid, ()))
            coverage.append(
                WikiNotebookCoverageDTO(
                    file_id=str(int_fid),
                    file_name=str(fname or ""),
                    ocr_pages=ocr_pages,
                    cited_pages=cited_pages,
                    avg_chars_per_page=round(float(avg_len or 0)),
                    cited_slugs=cited_slugs,
                )
            )
        coverage.sort(
            key=lambda c: (
                c.cited_pages / max(1, c.ocr_pages),
                -c.ocr_pages,
                c.file_name.lower(),
            )
        )
        return coverage

    async def list_dry_run_pages(
        self,
        user_id: int,
        *,
        file_id: int | None = None,
        start_date: str | None = None,
        offset_pages: int = 0,
        max_pages: int = 8,
    ) -> list[dict[str, Any]]:
        """Load a bounded slice of OCR pages for read-only dry-run compile inspection."""
        capped_pages = max(1, min(max_pages, 20))
        safe_offset = max(0, offset_pages)
        async with self._session_manager.session() as session:
            entries = await self._list_ordered_non_blank_pages(session, user_id)
            if file_id is not None:
                entries = [e for e in entries if e.file_id == file_id]
                entries.sort(key=lambda e: (e.page_index, e.row_id))
            if start_date is not None:
                entries = [
                    e for e in entries if format_page_date(e.page_ts_ms) >= start_date
                ]
            window = entries[safe_offset : safe_offset + capped_pages]
            if not window:
                return []
            return await self._build_page_window_diffs(session, user_id, window)
