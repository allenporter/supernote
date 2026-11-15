"""Unit tests for EventLogService append, cursor querying, and retention pruning."""

import time

import pytest

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded, LocalEventBus
from supernote.server.exceptions import CursorExpiredError, InvalidInputError
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.event_log import EventLogService


@pytest.fixture
def event_bus() -> LocalEventBus:
    return LocalEventBus()


@pytest.fixture
def event_log_service(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    event_bus: LocalEventBus,
) -> EventLogService:
    return EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        event_bus=event_bus,
        retention_days=90,
    )


async def test_append_persists_and_publishes_domain_event(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
) -> None:
    """Verify append commits monotonic seq rows and emits DomainEventRecorded."""
    published: list[DomainEventRecorded] = []

    async def on_recorded(ev: DomainEventRecorded) -> None:
        published.append(ev)

    event_bus.subscribe(DomainEventRecorded, on_recorded, inline=True)

    e1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="100",
        related_file_id=100,
        actor="device:SN001",
        payload={"path": "/NOTE/a.note"},
        timestamp_ms=1_700_000_001_000,
    )
    e2 = await event_log_service.append(
        user_id=1,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="100:0",
        related_file_id=100,
        actor="system:processor",
        payload={"page_index": 0, "current_text": "hello"},
        timestamp_ms=1_700_000_002_000,
    )

    assert e2.seq > e1.seq
    assert published == [e1, e2]


async def test_list_events_cursors_filters_and_user_isolation(
    event_log_service: EventLogService,
) -> None:
    """Verify cursor='0', cursor='head', pagination, type globbing, file_id, and exclude_actor."""
    empty_head = await event_log_service.list_events(user_id=1, cursor="head")
    assert empty_head.events == []
    assert empty_head.next_cursor == "0"
    assert empty_head.head_cursor == "0"
    assert empty_head.has_more is False

    ev1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="10",
        related_file_id=10,
        actor="device:SN1",
    )
    ev2 = await event_log_service.append(
        user_id=2,
        event_type="vfs.created",
        entity_type="file",
        entity_id="20",
        related_file_id=20,
        actor="user:web",
    )
    ev3 = await event_log_service.append(
        user_id=1,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="10:0",
        related_file_id=10,
        actor="system:processor",
    )
    ev4 = await event_log_service.append(
        user_id=1,
        event_type="schedule.task_created",
        entity_type="schedule_task",
        entity_id="t-1",
        actor="user:web",
    )
    assert ev1.seq < ev2.seq < ev3.seq < ev4.seq

    # User 1 sees only user 1 events; paginate 2 at a time
    page1 = await event_log_service.list_events(user_id=1, cursor="0", limit=2)
    assert [e.seq for e in page1.events] == [ev1.seq, ev3.seq]
    assert page1.has_more is True
    assert page1.next_cursor == str(ev3.seq)
    assert page1.head_cursor == str(ev4.seq)

    page2 = await event_log_service.list_events(
        user_id=1, cursor=page1.next_cursor, limit=2
    )
    assert [e.seq for e in page2.events] == [ev4.seq]
    assert page2.has_more is False
    assert page2.next_cursor == str(ev4.seq)

    # Prefix type globbing + exact type matching
    filtered_types = await event_log_service.list_events(
        user_id=1, cursor="0", types=["note.*", "schedule.task_created"]
    )
    assert [e.seq for e in filtered_types.events] == [ev3.seq, ev4.seq]

    # When a filtered query has 0 matches, next_cursor advances to head_cursor
    no_match = await event_log_service.list_events(
        user_id=1, cursor="0", types=["summary.*"]
    )
    assert no_match.events == []
    assert no_match.next_cursor == str(ev4.seq)
    assert no_match.head_cursor == str(ev4.seq)

    # file_id and exclude_actor filters
    by_file = await event_log_service.list_events(
        user_id=1, cursor="0", file_id=10, exclude_actor="device:SN1"
    )
    assert [e.seq for e in by_file.events] == [ev3.seq]

    # cursor="head" fast-forwards to user 1's latest seq
    head_page = await event_log_service.list_events(user_id=1, cursor="head")
    assert head_page.events == []
    assert head_page.next_cursor == str(ev4.seq)
    assert head_page.head_cursor == str(ev4.seq)


async def test_list_events_validation_errors(
    event_log_service: EventLogService,
) -> None:
    """Verify invalid cursors and out-of-range limits raise InvalidInputError."""
    for bad_cursor in ("", "-1", "abc", "12.3", "head "):
        with pytest.raises(InvalidInputError):
            await event_log_service.list_events(user_id=1, cursor=bad_cursor)

    for bad_limit in (0, -5, 1001):
        with pytest.raises(InvalidInputError):
            await event_log_service.list_events(user_id=1, limit=bad_limit)


async def test_prune_expired_events_and_cursor_expiration(
    event_log_service: EventLogService,
) -> None:
    """Verify pruning deletes expired history and raises 410 only for cursors < pruned_seq."""
    now_ms = int(time.time() * 1000)
    old1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 10_000,
    )
    old2 = await event_log_service.append(
        user_id=1,
        event_type="vfs.moved",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 8_000,
    )
    recent = await event_log_service.append(
        user_id=1,
        event_type="vfs.deleted",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 1_000,
    )

    deleted = await event_log_service.prune_expired_events(max_age_ms=5_000)
    assert deleted == 2

    # cursor < old2.seq is expired (410 Gone)
    with pytest.raises(CursorExpiredError) as exc_info:
        await event_log_service.list_events(user_id=1, cursor=str(old1.seq))
    assert exc_info.value.status_code == 410

    # cursor == old2.seq is still valid because client already consumed up through old2.seq
    from_boundary = await event_log_service.list_events(user_id=1, cursor=str(old2.seq))
    assert [e.seq for e in from_boundary.events] == [recent.seq]

    # cursor == "0" always returns retained history without raising 410
    from_zero = await event_log_service.list_events(user_id=1, cursor="0")
    assert [e.seq for e in from_zero.events] == [recent.seq]

    # Pruning again with no expired rows or disabled retention is a safe no-op
    assert await event_log_service.prune_expired_events(max_age_ms=5_000) == 0
    assert await event_log_service.prune_expired_events(max_age_ms=0) == 0
    assert await event_log_service.prune_expired_events() == 0


async def test_prune_disabled_when_retention_days_is_zero(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify retention_days=0 retains events indefinitely."""
    svc = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        retention_days=0,
    )
    await svc.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=1_000,
    )
    assert await svc.prune_expired_events() == 0
