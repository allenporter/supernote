"""Read-only aggregation service for the cross-notebook page timeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import select, tuple_

from supernote.models.events import DomainEventType
from supernote.models.timeline import (
    TimelineDayCountVO,
    TimelineDaysRequestDTO,
    TimelineDaysVO,
    TimelinePagesRequestDTO,
    TimelinePagesVO,
    TimelinePageVO,
)
from supernote.notebook import exceptions as notebook_exceptions
from supernote.notebook.schema import PageMetadata
from supernote.server.db.models.event_log import UserEventDO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import InvalidInputError
from supernote.server.utils.note_content import infer_page_created_ms

__all__ = [
    "TIMELINE_SERVICE_KEY",
    "TimelineService",
]

_MAX_LIMIT = 100
# Each (file_id, page_id) pair consumes 2 SQLite bind variables; 400 stays safely below 999.
_SQL_PAIR_BATCH_SIZE = 400


@dataclass
class _Entry:
    day: str
    timestamp_ms: int
    pm: NotePageMetadataDO
    file_name: str
    has_five_star: bool | None = None
    sources: set[str] = field(default_factory=set)

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.timestamp_ms, self.pm.file_id, self.pm.page_index)

    def to_vo(self) -> TimelinePageVO:
        five_star = (
            self.has_five_star
            if self.has_five_star is not None
            else _has_five_star(self.pm.page_json)
        )
        return TimelinePageVO(
            date=self.day,
            timestamp_ms=self.timestamp_ms,
            file_id=self.pm.file_id,
            file_name=self.file_name,
            page_index=self.pm.page_index,
            page_id=self.pm.page_id,
            sources=[s for s in ("created", "edited") if s in self.sources],
            is_blank=not self.pm.has_drawables,
            has_five_star=five_star,
            keywords=self.pm.keyword_texts,
        )


def _has_five_star(page_json: str) -> bool:
    if not page_json:
        return False
    try:
        raw = json.loads(page_json)
        return isinstance(raw, dict) and bool(PageMetadata.from_params(raw).five_star)
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        notebook_exceptions.ParserException,
    ):
        return False


def _resolve_bounds(
    req: TimelineDaysRequestDTO,
) -> tuple[timezone, int | None, int | None]:
    if not (-720 <= req.tz_offset_minutes <= 840):
        raise InvalidInputError("tzOffsetMinutes must be between -720 and 840")
    tz = timezone(timedelta(minutes=req.tz_offset_minutes))

    def _day_start_ms(raw: str, name: str, *, plus_days: int = 0) -> int:
        try:
            d = date.fromisoformat(raw.strip()) + timedelta(days=plus_days)
        except ValueError as err:
            raise InvalidInputError(
                f"Invalid {name} {raw!r}; expected YYYY-MM-DD"
            ) from err
        return int(datetime(d.year, d.month, d.day, tzinfo=tz).timestamp() * 1000)

    start_ms = _day_start_ms(req.start_date, "startDate") if req.start_date else None
    end_ms = (
        _day_start_ms(req.end_date, "endDate", plus_days=1) if req.end_date else None
    )
    if start_ms is not None and end_ms is not None and start_ms >= end_ms:
        raise InvalidInputError("startDate must be on or before endDate")
    return tz, start_ms, end_ms


def _parse_cursor(cursor: str | None) -> tuple[int, int, int] | None:
    if not cursor:
        return None
    parts = cursor.split(":")
    if len(parts) != 3:
        raise InvalidInputError(f"Invalid cursor {cursor!r}")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as err:
        raise InvalidInputError(f"Invalid cursor {cursor!r}") from err


class TimelineService:
    """Queries cross-notebook page creation and edit activity for a user."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    async def list_pages(
        self, user_id: int, req: TimelinePagesRequestDTO
    ) -> TimelinePagesVO:
        """Return paginated page activity entries ordered newest-first."""
        if not (1 <= req.limit <= _MAX_LIMIT):
            raise InvalidInputError(f"limit must be between 1 and {_MAX_LIMIT}")
        tz, start_ms, end_ms = _resolve_bounds(req)
        cursor_key = _parse_cursor(req.cursor)

        entries = await self._collect_entries(
            user_id=user_id,
            req=req,
            tz=tz,
            start_ms=start_ms,
            end_ms=end_ms,
            max_ts=cursor_key[0] if cursor_key else None,
        )
        entries.sort(key=lambda e: e.sort_key, reverse=True)
        if cursor_key is not None:
            entries = [e for e in entries if e.sort_key < cursor_key]

        has_more = len(entries) > req.limit
        page = entries[: req.limit]
        next_cursor = (
            f"{page[-1].timestamp_ms}:{page[-1].pm.file_id}:{page[-1].pm.page_index}"
            if has_more and page
            else None
        )
        return TimelinePagesVO(
            items=[e.to_vo() for e in page],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def list_days(
        self, user_id: int, req: TimelineDaysRequestDTO
    ) -> TimelineDaysVO:
        """Return per-day activity counts for calendar navigation."""
        tz, start_ms, end_ms = _resolve_bounds(req)
        entries = await self._collect_entries(
            user_id=user_id, req=req, tz=tz, start_ms=start_ms, end_ms=end_ms
        )
        counts: dict[str, list[int]] = {}
        for entry in entries:
            bucket = counts.setdefault(entry.day, [0, 0, 0])
            bucket[0] += 1
            bucket[1] += int("created" in entry.sources)
            bucket[2] += int("edited" in entry.sources)
        return TimelineDaysVO(
            days=[
                TimelineDayCountVO(
                    date=day, count=total, created_count=created, edited_count=edited
                )
                for day, (total, created, edited) in sorted(
                    counts.items(), reverse=True
                )
            ]
        )

    async def _collect_entries(
        self,
        *,
        user_id: int,
        req: TimelineDaysRequestDTO,
        tz: timezone,
        start_ms: int | None,
        end_ms: int | None,
        max_ts: int | None = None,
    ) -> list[_Entry]:
        merged: dict[tuple[str, int, int], _Entry] = {}

        async with self.session_manager.session() as session:
            # Created pages from f_note_page_metadata (inferred from <PAGEID>, fallback to file create_time).
            page_stmt = (
                select(NotePageMetadataDO, UserFileDO.file_name, UserFileDO.create_time)
                .join(
                    UserFileDO,
                    (NotePageMetadataDO.file_id == UserFileDO.id)
                    & (NotePageMetadataDO.user_id == UserFileDO.user_id),
                )
                .where(
                    NotePageMetadataDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "N",
                )
            )
            if not req.include_blank:
                page_stmt = page_stmt.where(NotePageMetadataDO.has_drawables.is_(True))

            for pm, file_name, file_create_time in (
                await session.execute(page_stmt)
            ).all():
                ts_ms = infer_page_created_ms(pm.page_id)
                if ts_ms is None:
                    ts_ms = file_create_time
                if start_ms is not None and ts_ms < start_ms:
                    continue
                if end_ms is not None and ts_ms >= end_ms:
                    continue
                if max_ts is not None and ts_ms > max_ts:
                    continue
                starred = _has_five_star(pm.page_json) if req.starred_only else None
                if req.starred_only and not starred:
                    continue
                day = datetime.fromtimestamp(ts_ms / 1000, tz=tz).strftime("%Y-%m-%d")
                merged[(day, pm.file_id, pm.page_index)] = _Entry(
                    day=day,
                    timestamp_ms=ts_ms,
                    pm=pm,
                    file_name=file_name,
                    has_five_star=starred,
                    sources={"created"},
                )

            # Edited pages from note.pages_delta events in f_user_event.
            ev_stmt = select(
                UserEventDO.related_file_id,
                UserEventDO.timestamp_ms,
                UserEventDO.payload,
            ).where(
                UserEventDO.user_id == user_id,
                UserEventDO.event_type == DomainEventType.NOTE_PAGES_DELTA.value,
                UserEventDO.related_file_id.is_not(None),
            )
            if start_ms is not None:
                ev_stmt = ev_stmt.where(UserEventDO.timestamp_ms >= start_ms)
            if end_ms is not None:
                ev_stmt = ev_stmt.where(UserEventDO.timestamp_ms < end_ms)
            if max_ts is not None:
                ev_stmt = ev_stmt.where(UserEventDO.timestamp_ms <= max_ts)

            edit_hits: dict[tuple[str, int, str], int] = {}
            pairs: set[tuple[int, str]] = set()
            for rel_fid, ev_ts, payload in (await session.execute(ev_stmt)).all():
                if rel_fid is None or not isinstance(payload, dict):
                    continue
                day = datetime.fromtimestamp(ev_ts / 1000, tz=tz).strftime("%Y-%m-%d")
                for pid in payload.get("modified_pages") or ():
                    if isinstance(pid, str) and pid:
                        hit = (day, rel_fid, pid)
                        if ev_ts > edit_hits.get(hit, -1):
                            edit_hits[hit] = ev_ts
                        pairs.add((rel_fid, pid))

            if pairs:
                meta_by_pair: dict[tuple[int, str], tuple[NotePageMetadataDO, str]] = {}
                pair_list = list(pairs)
                for i in range(0, len(pair_list), _SQL_PAIR_BATCH_SIZE):
                    batch_stmt = (
                        select(NotePageMetadataDO, UserFileDO.file_name)
                        .join(
                            UserFileDO,
                            (NotePageMetadataDO.file_id == UserFileDO.id)
                            & (NotePageMetadataDO.user_id == UserFileDO.user_id),
                        )
                        .where(
                            NotePageMetadataDO.user_id == user_id,
                            UserFileDO.is_active == "Y",
                            UserFileDO.is_folder == "N",
                            tuple_(
                                NotePageMetadataDO.file_id, NotePageMetadataDO.page_id
                            ).in_(pair_list[i : i + _SQL_PAIR_BATCH_SIZE]),
                        )
                    )
                    if not req.include_blank:
                        batch_stmt = batch_stmt.where(
                            NotePageMetadataDO.has_drawables.is_(True)
                        )
                    for pm, file_name in (await session.execute(batch_stmt)).all():
                        meta_by_pair[(pm.file_id, pm.page_id)] = (pm, file_name)

                for (day, rel_fid, pid), ev_ts in edit_hits.items():
                    resolved = meta_by_pair.get((rel_fid, pid))
                    if resolved is None:
                        continue
                    pm, file_name = resolved
                    starred = _has_five_star(pm.page_json) if req.starred_only else None
                    if req.starred_only and not starred:
                        continue
                    key = (day, pm.file_id, pm.page_index)
                    existing = merged.get(key)
                    if existing is not None:
                        existing.sources.add("edited")
                        existing.timestamp_ms = max(existing.timestamp_ms, ev_ts)
                    else:
                        merged[key] = _Entry(
                            day=day,
                            timestamp_ms=ev_ts,
                            pm=pm,
                            file_name=file_name,
                            has_five_star=starred,
                            sources={"edited"},
                        )

        return list(merged.values())


TIMELINE_SERVICE_KEY = web.AppKey("timeline_service", TimelineService)
