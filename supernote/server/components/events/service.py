"""Append-only domain event log storage, cursor query, and retention service.

This module implements `EventLogService`, the transport-free domain service
backing the `events` vertical component (`supernote.server.components.events`).

### Event Persistence Pipeline

1. Domain services publish `supernote.server.events.DomainEvent` subclasses
   (enumerated in `SUBSCRIBED_DOMAIN_EVENTS`) onto the core `LocalEventBus`.
2. `EventLogService` subscribes inline to those events, persists an ordered
   `supernote.server.db.models.event_log.UserEventDO` row in `f_user_event`
   with a monotonically increasing `seq`, and immediately publishes a
   `DomainEventRecorded` notification onto `LocalEventBus` (consumed by
   downstream listeners such as `SocketIOServerManager` to push lightweight
   `event_log_cursor` notifications).
3. Consumers query per-user history incrementally via `EventLogService.list_events`
   using opaque `v1:<seq>` sync tokens (`EventFeedPage`), with optional
   filtering by `event_types` (exact or `<namespace>.*` wildcards), `file_id`,
   and `exclude_actors` (for echo suppression).
4. When started via `EventLogService.start`, a background task periodically
   calls `prune_expired_events` to delete rows older than `retention_days` and
   records a durable `event_log:pruned_seq` watermark in `CoordinationService`
   so stale client cursors receive `CursorExpiredError` (HTTP 410 Gone).

### Internal Component Access

Other server components or plugins declaring `dependencies = ("events",)` can
retrieve the shared service instance via `core.app[EVENT_LOG_SERVICE_KEY]`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from aiohttp import web
from sqlalchemy import delete, func, or_, select

from supernote.server.db.models.event_log import UserEventDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    DomainEvent,
    DomainEventRecorded,
    LocalEventBus,
    NotePagesDeltaEvent,
    NotePageTranscribedEvent,
    NoteProcessingCompletedEvent,
    NoteProcessingFailedEvent,
    ScheduleTaskCreatedEvent,
    ScheduleTaskDeletedEvent,
    ScheduleTaskUpdatedEvent,
    SummaryDeletedEvent,
    SummaryUpsertedEvent,
    VfsContentUpdatedEvent,
    VfsItemCopiedEvent,
    VfsItemCreatedEvent,
    VfsItemDeletedEvent,
    VfsItemMovedEvent,
)
from supernote.server.exceptions import CursorExpiredError, InvalidInputError
from supernote.server.services.coordination import CoordinationService

from .models import (
    DEFAULT_EVENT_LOG_RETENTION_DAYS,
    DEFAULT_FEED_LIMIT,
    MAX_FEED_LIMIT,
    EventFeedPage,
    decode_sync_token,
    encode_sync_token,
)

__all__ = [
    "EVENT_LOG_SERVICE_KEY",
    "EventLogService",
]

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LOG_PRUNE_INTERVAL_SECONDS = 300.0
"""Default interval in seconds between background retention pruning sweeps."""

_PRUNED_SEQ_KEY = "event_log:pruned_seq"
_PRUNED_SEQ_TTL = 100 * 365 * 86400

SUBSCRIBED_DOMAIN_EVENTS: tuple[type[DomainEvent], ...] = (
    VfsItemCreatedEvent,
    VfsContentUpdatedEvent,
    VfsItemMovedEvent,
    VfsItemCopiedEvent,
    VfsItemDeletedEvent,
    ScheduleTaskCreatedEvent,
    ScheduleTaskUpdatedEvent,
    ScheduleTaskDeletedEvent,
    SummaryUpsertedEvent,
    SummaryDeletedEvent,
    NotePagesDeltaEvent,
    NotePageTranscribedEvent,
    NoteProcessingCompletedEvent,
    NoteProcessingFailedEvent,
)
"""Canonical tuple of `DomainEvent` subclasses persisted into `f_user_event`."""


class EventLogService:
    """Persists, queries, and prunes per-user domain events (`f_user_event`).

    All query operations are strictly scoped by `user_id`. When constructed
    with a `LocalEventBus`, the service immediately subscribes inline to every
    event type in `SUBSCRIBED_DOMAIN_EVENTS` so events emitted during startup
    or tests are never missed. Call `start()` and `stop()` to manage the
    periodic retention-pruning background task.
    """

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        coordination_service: CoordinationService,
        event_bus: LocalEventBus | None = None,
        retention_days: int = DEFAULT_EVENT_LOG_RETENTION_DAYS,
        prune_interval_seconds: float = DEFAULT_EVENT_LOG_PRUNE_INTERVAL_SECONDS,
    ) -> None:
        """Initialize the event log service and subscribe to domain events.

        Args:
            session_manager: Async SQLAlchemy session manager for `f_user_event`.
            coordination_service: TTL KV store used to persist the
                `event_log:pruned_seq` retention watermark.
            event_bus: Optional core `LocalEventBus` to subscribe to
                `SUBSCRIBED_DOMAIN_EVENTS` and publish `DomainEventRecorded`.
            retention_days: Number of days to retain event rows before pruning.
                Set to `0` to retain history indefinitely (disables background
                pruning).
            prune_interval_seconds: Positive interval in seconds between
                background retention sweeps when `start()` is active.

        Raises:
            ValueError: If `prune_interval_seconds <= 0`.
        """
        if prune_interval_seconds <= 0:
            raise ValueError("prune_interval_seconds must be positive")
        self._session_manager = session_manager
        self._coordination_service = coordination_service
        self._event_bus = event_bus
        self._retention_days = retention_days
        self._prune_interval_seconds = prune_interval_seconds
        self._shutdown_event = asyncio.Event()
        self._prune_task: asyncio.Task[None] | None = None
        if self._event_bus is not None:
            for event_cls in SUBSCRIBED_DOMAIN_EVENTS:
                self._event_bus.subscribe(event_cls, self._on_domain_event, inline=True)

    async def start(self) -> None:
        """Start the periodic background retention-pruning loop.

        Idempotent: calling `start()` when already running is a no-op. Also a
        no-op when `retention_days <= 0` (infinite retention).
        """
        if self._retention_days <= 0:
            return
        if self._prune_task is not None and not self._prune_task.done():
            return
        self._shutdown_event.clear()
        self._prune_task = asyncio.create_task(
            self._prune_loop(),
            name="event-log-pruner",
        )

    async def stop(self) -> None:
        """Idempotently stop the background retention-pruning loop."""
        self._shutdown_event.set()
        task = self._prune_task
        self._prune_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _prune_loop(self) -> None:
        try:
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self._prune_interval_seconds,
                    )
                    break
                except TimeoutError:
                    pass
                try:
                    pruned = await self.prune_expired_events()
                    if pruned > 0:
                        logger.info("Pruned %d expired domain events", pruned)
                except Exception:
                    logger.exception("Error pruning expired domain events")
        except asyncio.CancelledError:
            pass

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
        """Append a domain event row and publish `DomainEventRecorded` once committed.

        Args:
            user_id: Owner user ID for the event.
            event_type: Dotted event type identifier (see
                `supernote.models.events.DomainEventType`).
            entity_type: Primary entity category (see
                `supernote.models.events.DomainEntityType`).
            entity_id: String identifier of the affected entity.
            payload: Optional JSON-serializable event metadata dictionary.
            actor: Caller actor attribution string (e.g., ``"user:web"``,
                ``"device:<serial>"``, ``"api_key:<id>"``, ``"system:processor"``).
            related_file_id: Optional VFS `UserFileDO.id` associated with the
                event, enabling per-file feed filtering.
            timestamp_ms: Optional Unix epoch timestamp in milliseconds;
                defaults to the current wall-clock time.

        Returns:
            The committed `DomainEventRecorded` instance including its assigned
            monotonic `seq`.
        """
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
        sync_token: str | None = None,
        event_types: list[str] | None = None,
        file_id: int | None = None,
        exclude_actors: list[str] | None = None,
        limit: int = DEFAULT_FEED_LIMIT,
    ) -> EventFeedPage:
        """Query a user's domain event feed incrementally after `sync_token`.

        Args:
            user_id: Owner user ID whose event log to query.
            sync_token: Opaque `next_sync_token` returned by a previous call.
                When `None` or empty, returns retained events from the beginning.
            event_types: Optional list of event type filters supporting exact
                `DomainEventType` values (defined in `supernote.models.events`)
                or namespace prefix wildcards ending with ``'.*'`` (``'note.*'``,
                ``'vfs.*'``, ``'schedule.*'``, ``'summary.*'``).
            file_id: Optional VFS file ID filter (`related_file_id == file_id`).
            exclude_actors: Optional list of actor identifiers to omit from
                results (e.g., ``['api_key:<id>']``). Filtered events still
                advance `next_sync_token` so callers do not re-scan their own
                mutations.
            limit: Maximum number of events to return (`1..MAX_FEED_LIMIT`,
                default `DEFAULT_FEED_LIMIT`).

        Returns:
            An `EventFeedPage` containing the ordered events, `next_sync_token`
            checkpoint, and `has_more` pagination flag.

        Raises:
            InvalidInputError: If `sync_token` is malformed or `limit` is outside
                `1..MAX_FEED_LIMIT` (HTTP 400).
            CursorExpiredError: If `sync_token` predates the retained event log
                window after pruning (HTTP 410 Gone); callers should discard the
                expired token, perform a full state resync, and resume from the
                new `next_sync_token`.
        """
        if limit < 1 or limit > MAX_FEED_LIMIT:
            raise InvalidInputError(f"limit must be between 1 and {MAX_FEED_LIMIT}")

        after_seq = 0
        if sync_token:
            after_seq = decode_sync_token(sync_token)
            pruned_seq = await self._get_pruned_seq()
            if after_seq < pruned_seq:
                raise CursorExpiredError(
                    "Sync token has expired (predates retained event history)"
                )

        async with self._session_manager.session() as session:
            stmt = select(UserEventDO).where(
                UserEventDO.user_id == user_id,
                UserEventDO.seq > after_seq,
            )
            if file_id is not None:
                stmt = stmt.where(UserEventDO.related_file_id == file_id)
            if exclude_actors:
                excluded = [a for a in exclude_actors if a]
                if excluded:
                    stmt = stmt.where(UserEventDO.actor.notin_(excluded))
            if event_types:
                type_clauses = [
                    UserEventDO.event_type.startswith(t[:-1], autoescape=True)
                    if t.endswith(".*")
                    else UserEventDO.event_type == t
                    for t in event_types
                    if t
                ]
                if type_clauses:
                    stmt = stmt.where(or_(*type_clauses))

            stmt = stmt.order_by(UserEventDO.seq.asc()).limit(limit + 1)
            rows = list((await session.execute(stmt)).scalars().all())

            has_more = len(rows) > limit
            page_rows = rows[:limit]
            if page_rows:
                next_sync_token: str | None = encode_sync_token(int(page_rows[-1].seq))
            else:
                max_user_seq = await session.scalar(
                    select(func.max(UserEventDO.seq)).where(
                        UserEventDO.user_id == user_id
                    )
                )
                effective_seq = max(after_seq, int(max_user_seq or 0))
                next_sync_token = (
                    encode_sync_token(effective_seq) if effective_seq > 0 else None
                )

        return EventFeedPage(
            events=[_row_to_recorded(row) for row in page_rows],
            next_sync_token=next_sync_token,
            has_more=has_more,
        )

    async def prune_expired_events(self, *, max_age_ms: int | None = None) -> int:
        """Delete events older than the retention window and advance the pruned watermark.

        Records the highest deleted `seq` in `CoordinationService` under
        `event_log:pruned_seq` *before* deleting rows so concurrent readers with
        older cursors reliably observe `CursorExpiredError` rather than silently
        missing pruned history.

        Args:
            max_age_ms: Optional explicit retention window in milliseconds,
                overriding `retention_days` (useful for tests and administrative
                sweeps). Values `<= 0` perform no deletion.

        Returns:
            Number of `UserEventDO` rows deleted.
        """
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

    async def _on_domain_event(self, event: DomainEvent) -> None:
        await self.append(
            user_id=event.user_id,
            event_type=event.EVENT_TYPE,
            entity_type=event.ENTITY_TYPE,
            entity_id=event.entity_id,
            actor=event.actor,
            related_file_id=event.related_file_id,
            payload=event.to_payload(),
        )


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


EVENT_LOG_SERVICE_KEY: web.AppKey[EventLogService] = web.AppKey("event_log_service")
"""Typed `aiohttp.web.AppKey` exposing `EventLogService` to sibling components and routes."""
