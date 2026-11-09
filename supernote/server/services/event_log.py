"""Append-only domain event log storage and cursor query service."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, or_, select

from supernote.server.db.models.event_log import UserEventDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded, LocalEventBus
from supernote.server.exceptions import CursorExpiredError, InvalidInputError
from supernote.server.services.coordination import CoordinationService

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LOG_RETENTION_DAYS = 90
DEFAULT_FEED_LIMIT = 200
MAX_FEED_LIMIT = 1000

_PRUNED_SEQ_KEY = "event_log:pruned_seq"
_PRUNED_SEQ_TTL = 100 * 365 * 86400


@dataclass(slots=True)
class EventFeedPage:
    """Paginated cursor response for per-user domain event queries."""

    events: list[DomainEventRecorded]
    next_cursor: str
    head_cursor: str
    has_more: bool


class EventLogService:
    """Persists and queries per-user domain events (`f_user_event`)."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        coordination_service: CoordinationService,
        event_bus: LocalEventBus | None = None,
        retention_days: int = DEFAULT_EVENT_LOG_RETENTION_DAYS,
    ) -> None:
        self._session_manager = session_manager
        self._coordination_service = coordination_service
        self._event_bus = event_bus
        self._retention_days = retention_days

    async def append(
        self,
        *,
        user_id: int,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        actor: str = "user:web",
        related_file_id: int | None = None,
        timestamp_ms: int | None = None,
    ) -> DomainEventRecorded:
        """Append a domain event row and publish `DomainEventRecorded` once committed."""
        ts_ms = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        payload_dict = dict(payload) if payload else {}

        async with self._session_manager.session() as session:
            row = UserEventDO(
                user_id=user_id,
                timestamp_ms=ts_ms,
                event_type=event_type,
                actor=actor,
                entity_type=entity_type,
                entity_id=entity_id,
                related_file_id=related_file_id,
                payload=payload_dict,
            )
            session.add(row)
            await session.commit()
            seq = int(row.seq)

        recorded = DomainEventRecorded(
            user_id=user_id,
            seq=seq,
            timestamp_ms=ts_ms,
            event_type=event_type,
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            related_file_id=related_file_id,
            payload=payload_dict,
        )
        if self._event_bus is not None:
            await self._event_bus.publish(recorded)
        return recorded

    async def list_events(
        self,
        user_id: int,
        *,
        cursor: str = "0",
        types: list[str] | None = None,
        file_id: int | None = None,
        exclude_actor: str | None = None,
        limit: int = DEFAULT_FEED_LIMIT,
    ) -> EventFeedPage:
        """Query a user's domain event feed after `cursor`."""
        if limit < 1 or limit > MAX_FEED_LIMIT:
            raise InvalidInputError(f"limit must be between 1 and {MAX_FEED_LIMIT}")

        if cursor != "head" and not (cursor.isascii() and cursor.isdigit()):
            raise InvalidInputError(f"Invalid cursor: {cursor!r}")

        pruned_seq = await self._get_pruned_seq()

        async with self._session_manager.session() as session:
            max_user_seq = await session.scalar(
                select(func.max(UserEventDO.seq)).where(UserEventDO.user_id == user_id)
            )
            head_seq = max(int(max_user_seq or 0), pruned_seq)

            if cursor == "head":
                return EventFeedPage(
                    events=[],
                    next_cursor=str(head_seq),
                    head_cursor=str(head_seq),
                    has_more=False,
                )

            cursor_seq = int(cursor)
            if 0 < cursor_seq < pruned_seq:
                raise CursorExpiredError(
                    f"Cursor {cursor_seq} has expired (oldest retained seq is {pruned_seq})"
                )

            stmt = select(UserEventDO).where(
                UserEventDO.user_id == user_id,
                UserEventDO.seq > cursor_seq,
            )
            if file_id is not None:
                stmt = stmt.where(UserEventDO.related_file_id == file_id)
            if exclude_actor:
                stmt = stmt.where(UserEventDO.actor != exclude_actor)
            if types:
                type_clauses = [
                    UserEventDO.event_type.startswith(t[:-1], autoescape=True)
                    if t.endswith(".*")
                    else UserEventDO.event_type == t
                    for t in types
                    if t
                ]
                if type_clauses:
                    stmt = stmt.where(or_(*type_clauses))

            stmt = stmt.order_by(UserEventDO.seq.asc()).limit(limit + 1)
            rows = list((await session.execute(stmt)).scalars().all())

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        if page_rows:
            last_seq = int(page_rows[-1].seq)
            head_seq = max(head_seq, last_seq)
            next_cursor = str(last_seq)
        else:
            next_cursor = str(max(cursor_seq, head_seq))

        return EventFeedPage(
            events=[_row_to_recorded(row) for row in page_rows],
            next_cursor=next_cursor,
            head_cursor=str(head_seq),
            has_more=has_more,
        )

    async def prune_expired_events(self, *, max_age_ms: int | None = None) -> int:
        """Delete events older than the retention window and record the pruned watermark."""
        if max_age_ms is not None:
            age_ms = max_age_ms
        elif self._retention_days <= 0:
            return 0
        else:
            age_ms = self._retention_days * 86_400_000

        if age_ms <= 0:
            return 0

        cutoff_ms = int(time.time() * 1000) - age_ms

        async with self._session_manager.session() as session:
            cutoff_seq = await session.scalar(
                select(func.max(UserEventDO.seq)).where(
                    UserEventDO.timestamp_ms < cutoff_ms
                )
            )
            if cutoff_seq is None:
                return 0

            pruned_seq = max(await self._get_pruned_seq(), int(cutoff_seq))
            await self._coordination_service.set_value(
                _PRUNED_SEQ_KEY, str(pruned_seq), ttl=_PRUNED_SEQ_TTL
            )

            result = await session.execute(
                delete(UserEventDO).where(UserEventDO.seq <= int(cutoff_seq))
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

    async def _get_pruned_seq(self) -> int:
        raw = await self._coordination_service.get_value(_PRUNED_SEQ_KEY)
        if raw and raw.isascii() and raw.isdigit():
            return int(raw)
        return 0


def _row_to_recorded(row: UserEventDO) -> DomainEventRecorded:
    return DomainEventRecorded(
        user_id=int(row.user_id),
        seq=int(row.seq),
        timestamp_ms=int(row.timestamp_ms),
        event_type=row.event_type,
        actor=row.actor,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        related_file_id=int(row.related_file_id)
        if row.related_file_id is not None
        else None,
        payload=dict(row.payload) if isinstance(row.payload, dict) else {},
    )
