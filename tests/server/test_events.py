"""Unit tests for LocalEventBus and server domain events."""

import asyncio

import pytest

from supernote.models.base import BooleanEnum
from supernote.models.summary import SummaryItem, SummaryTagItem
from supernote.server.events import (
    DomainEventRecorded,
    Event,
    LocalEventBus,
    NoteDeletedEvent,
    NoteProcessingCompletedEvent,
    NoteUpdatedEvent,
    ScheduleUpdatedEvent,
    SummaryDeletedEvent,
    SummaryTagDeletedEvent,
    SummaryTagUpsertedEvent,
    SummaryUpsertedEvent,
    SyncCompletedEvent,
    VfsItemCopiedEvent,
    VfsItemCreatedEvent,
    VfsItemDeletedEvent,
    VfsItemMovedEvent,
)


async def test_local_event_bus_publish_and_subscribe() -> None:
    bus = LocalEventBus()
    received_updated: list[NoteUpdatedEvent] = []
    received_deleted: list[NoteDeletedEvent] = []
    received_completed: list[NoteProcessingCompletedEvent] = []
    received_sync: list[SyncCompletedEvent] = []
    received_schedule: list[ScheduleUpdatedEvent] = []
    received_tag_upserted: list[SummaryTagUpsertedEvent] = []
    received_tag_deleted: list[SummaryTagDeletedEvent] = []
    received_summary_upserted: list[SummaryUpsertedEvent] = []
    received_summary_deleted: list[SummaryDeletedEvent] = []
    received_vfs_created: list[VfsItemCreatedEvent] = []
    received_vfs_moved: list[VfsItemMovedEvent] = []
    received_vfs_copied: list[VfsItemCopiedEvent] = []
    received_vfs_deleted: list[VfsItemDeletedEvent] = []

    async def on_updated(event: NoteUpdatedEvent) -> None:
        received_updated.append(event)

    async def on_deleted(event: NoteDeletedEvent) -> None:
        received_deleted.append(event)

    async def on_processing_completed(event: NoteProcessingCompletedEvent) -> None:
        received_completed.append(event)

    async def on_sync_completed(event: SyncCompletedEvent) -> None:
        received_sync.append(event)

    async def on_schedule_updated(event: ScheduleUpdatedEvent) -> None:
        received_schedule.append(event)

    async def on_tag_upserted(event: SummaryTagUpsertedEvent) -> None:
        received_tag_upserted.append(event)

    async def on_tag_deleted(event: SummaryTagDeletedEvent) -> None:
        received_tag_deleted.append(event)

    async def on_summary_upserted(event: SummaryUpsertedEvent) -> None:
        received_summary_upserted.append(event)

    async def on_summary_deleted(event: SummaryDeletedEvent) -> None:
        received_summary_deleted.append(event)

    async def on_vfs_created(event: VfsItemCreatedEvent) -> None:
        received_vfs_created.append(event)

    async def on_vfs_moved(event: VfsItemMovedEvent) -> None:
        received_vfs_moved.append(event)

    async def on_vfs_copied(event: VfsItemCopiedEvent) -> None:
        received_vfs_copied.append(event)

    async def on_vfs_deleted(event: VfsItemDeletedEvent) -> None:
        received_vfs_deleted.append(event)

    bus.subscribe(NoteUpdatedEvent, on_updated)
    bus.subscribe(NoteDeletedEvent, on_deleted)
    bus.subscribe(NoteProcessingCompletedEvent, on_processing_completed)
    bus.subscribe(SyncCompletedEvent, on_sync_completed)
    bus.subscribe(ScheduleUpdatedEvent, on_schedule_updated)
    bus.subscribe(SummaryTagUpsertedEvent, on_tag_upserted)
    bus.subscribe(SummaryTagDeletedEvent, on_tag_deleted)
    bus.subscribe(SummaryUpsertedEvent, on_summary_upserted)
    bus.subscribe(SummaryDeletedEvent, on_summary_deleted)
    bus.subscribe(VfsItemCreatedEvent, on_vfs_created)
    bus.subscribe(VfsItemMovedEvent, on_vfs_moved)
    bus.subscribe(VfsItemCopiedEvent, on_vfs_copied)
    bus.subscribe(VfsItemDeletedEvent, on_vfs_deleted)

    ev_updated = NoteUpdatedEvent(
        file_id=10, user_id=1, file_path="/Note/a.note", defer_processing=True
    )
    ev_deleted = NoteDeletedEvent(file_id=10, user_id=1)
    ev_completed = NoteProcessingCompletedEvent(
        file_id=10, user_id=1, file_path="/Note/a.note"
    )
    ev_sync = SyncCompletedEvent(user_id=1, equipment_no="SN123")
    ev_schedule = ScheduleUpdatedEvent(
        user_id=1, task_list_id="group-1", task_id="task-2", equipment_no="SN123"
    )
    ev_tag_upserted = SummaryTagUpsertedEvent(
        user_id=1,
        tag=SummaryTagItem(id=5, name="Work", user_id=1, unique_identifier="tag-u1"),
        is_new=True,
    )
    ev_tag_deleted = SummaryTagDeletedEvent(user_id=1, tag_id=5)
    ev_summary_upserted = SummaryUpsertedEvent(
        user_id=1,
        summary=SummaryItem(
            id=8,
            user_id=1,
            unique_identifier="sum-u1",
            is_summary_group=BooleanEnum.NO,
        ),
        is_new=True,
    )
    ev_summary_deleted = SummaryDeletedEvent(
        user_id=1, summary_id=8, is_summary_group=False
    )
    ev_vfs_created = VfsItemCreatedEvent(
        user_id=1,
        item_id=11,
        parent_id=0,
        name="a.note",
        is_folder=False,
        full_path="a.note",
        size=128,
        md5="abc",
    )
    ev_vfs_moved = VfsItemMovedEvent(
        user_id=1,
        item_id=11,
        original_parent_id=0,
        new_parent_id=2,
        original_name="a.note",
        new_name="b.note",
        original_full_path="a.note",
        new_full_path="Folder/b.note",
        is_folder=False,
        size=128,
        md5="abc",
    )
    ev_vfs_copied = VfsItemCopiedEvent(
        user_id=1,
        source_id=11,
        new_id=12,
        source_parent_id=0,
        new_parent_id=2,
        original_name="a.note",
        new_name="a(1).note",
        original_full_path="a.note",
        new_full_path="Folder/a(1).note",
        is_folder=False,
        size=128,
        md5="abc",
    )
    ev_vfs_deleted = VfsItemDeletedEvent(
        user_id=1,
        item_id=12,
        parent_id=2,
        name="a(1).note",
        full_path="Folder/a(1).note",
        is_folder=False,
        size=128,
        md5="abc",
    )

    # Publishing an event with no subscribers is a safe no-op
    await bus.publish(Event())

    await bus.publish(ev_updated)
    await bus.publish(ev_deleted)
    await bus.publish(ev_completed)
    await bus.publish(ev_sync)
    await bus.publish(ev_schedule)
    await bus.publish(ev_tag_upserted)
    await bus.publish(ev_tag_deleted)
    await bus.publish(ev_summary_upserted)
    await bus.publish(ev_summary_deleted)
    await bus.publish(ev_vfs_created)
    await bus.publish(ev_vfs_moved)
    await bus.publish(ev_vfs_copied)
    await bus.publish(ev_vfs_deleted)
    await asyncio.sleep(0)

    assert received_updated == [ev_updated]
    assert received_deleted == [ev_deleted]
    assert received_completed == [ev_completed]
    assert received_sync == [ev_sync]
    assert received_schedule == [ev_schedule]
    assert received_tag_upserted == [ev_tag_upserted]
    assert received_tag_deleted == [ev_tag_deleted]
    assert received_summary_upserted == [ev_summary_upserted]
    assert received_summary_deleted == [ev_summary_deleted]
    assert received_vfs_created == [ev_vfs_created]
    assert received_vfs_moved == [ev_vfs_moved]
    assert received_vfs_copied == [ev_vfs_copied]
    assert received_vfs_deleted == [ev_vfs_deleted]


async def test_local_event_bus_isolates_subscriber_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = LocalEventBus()
    healthy_received: list[SyncCompletedEvent] = []

    async def failing_handler(event: SyncCompletedEvent) -> None:
        raise RuntimeError("subscriber boom")

    async def healthy_handler(event: SyncCompletedEvent) -> None:
        healthy_received.append(event)

    bus.subscribe(SyncCompletedEvent, failing_handler)
    bus.subscribe(SyncCompletedEvent, healthy_handler)

    ev = SyncCompletedEvent(user_id=42)
    await bus.publish(ev)
    await asyncio.sleep(0)

    assert healthy_received == [ev]
    assert "Error handling event" in caplog.text


async def test_local_event_bus_inline_subscribers_execute_in_order() -> None:
    """Verify inline=True subscribers run synchronously before publish returns."""
    bus = LocalEventBus()
    order: list[str] = []

    async def inline_first(event: DomainEventRecorded) -> None:
        order.append(f"inline_1:{event.seq}")

    async def inline_second(event: DomainEventRecorded) -> None:
        order.append(f"inline_2:{event.seq}")

    async def background_handler(event: DomainEventRecorded) -> None:
        order.append(f"bg:{event.seq}")

    bus.subscribe(DomainEventRecorded, inline_first, inline=True)
    bus.subscribe(DomainEventRecorded, background_handler, inline=False)
    bus.subscribe(DomainEventRecorded, inline_second, inline=True)

    recorded = DomainEventRecorded(
        user_id=1,
        seq=7,
        timestamp_ms=1000,
        event_type="vfs.created",
        actor="user:web",
        entity_type="file",
        entity_id="99",
    )
    await bus.publish(recorded)
    assert order == ["inline_1:7", "inline_2:7"]

    await asyncio.sleep(0)
    assert order == ["inline_1:7", "inline_2:7", "bg:7"]
