"""Component service event-diff tests for `supernote.server.components.schedule`."""

from __future__ import annotations

from supernote.server.components.schedule import SCHEDULE_SERVICE_KEY
from supernote.server.core import ServerCore
from supernote.server.events import (
    ScheduleTaskUpdatedEvent,
    ScheduleUpdatedEvent,
)
from tests.server.components.conftest import LoadComponents


async def test_schedule_service_publishes_domain_events_and_skips_noops(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify ScheduleService publishes ScheduleUpdatedEvent on mutations and skips failed/no-op calls."""
    await load_components("schedule")
    service = component_core.app[SCHEDULE_SERVICE_KEY]

    published: list[ScheduleUpdatedEvent] = []

    async def on_schedule_updated(event: ScheduleUpdatedEvent) -> None:
        published.append(event)

    component_core.event_bus.subscribe(
        ScheduleUpdatedEvent, on_schedule_updated, inline=True
    )

    # Non-existent mutations and empty batch updates must NOT publish events
    assert await service.update_group(test_user_id, "missing-group", "Title") is None
    assert await service.delete_group(test_user_id, "missing-group") is False
    assert await service.clear_group_tasks(test_user_id, "missing-group") is False
    assert await service.update_task(test_user_id, "missing-task", title="X") is None
    assert await service.delete_task(test_user_id, "missing-task") is False
    assert await service.batch_update_tasks(test_user_id, []) is True
    assert (
        await service.batch_update_tasks(test_user_id, [{"title": "No Task ID"}])
        is True
    )
    assert published == []

    # Create group -> publishes group event
    group = await service.create_group(test_user_id, "Event Group")
    assert published == [
        ScheduleUpdatedEvent(
            user_id=test_user_id,
            task_list_id=group.task_list_id,
            task_id=None,
            equipment_no=None,
        )
    ]
    published.clear()

    # Clearing an already-empty group is a no-op -> does NOT publish
    assert await service.clear_group_tasks(test_user_id, group.task_list_id) is False
    assert published == []

    # Create task -> publishes task event
    task = await service.create_task(test_user_id, group.task_list_id, "Task A")
    assert published == [
        ScheduleUpdatedEvent(
            user_id=test_user_id,
            task_list_id=group.task_list_id,
            task_id=task.task_id,
            equipment_no=None,
        )
    ]
    published.clear()

    # Batch update with no allowed fields is a no-op -> does NOT publish
    assert (
        await service.batch_update_tasks(
            test_user_id, [{"task_id": task.task_id, "unknown_field": "x"}]
        )
        is True
    )
    assert published == []

    # Clearing a non-empty group -> publishes group event
    assert await service.clear_group_tasks(test_user_id, group.task_list_id) is True
    assert published == [
        ScheduleUpdatedEvent(
            user_id=test_user_id,
            task_list_id=group.task_list_id,
            task_id=None,
            equipment_no=None,
        )
    ]


async def test_batch_update_tasks_tracks_sequential_changes_for_same_task(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify repeated updates to the same task_id in one batch diff against prior in-batch state."""
    await load_components("schedule")
    service = component_core.app[SCHEDULE_SERVICE_KEY]

    updated_events: list[ScheduleTaskUpdatedEvent] = []

    async def on_task_updated(event: ScheduleTaskUpdatedEvent) -> None:
        updated_events.append(event)

    component_core.event_bus.subscribe(
        ScheduleTaskUpdatedEvent, on_task_updated, inline=True
    )

    task = await service.create_task(test_user_id, None, "Draft v1")
    await service.batch_update_tasks(
        test_user_id,
        [
            {"task_id": task.task_id, "title": "Draft v2"},
            {"task_id": task.task_id, "status": "completed"},
        ],
    )

    assert [ev.to_payload() for ev in updated_events] == [
        {
            "task_id": task.task_id,
            "task_list_id": None,
            "title": "Draft v2",
            "detail": "",
            "status": "needsAction",
            "due_time": None,
            "links": None,
            "changed_fields": {"title": ["Draft v1", "Draft v2"]},
        },
        {
            "task_id": task.task_id,
            "task_list_id": None,
            "title": "Draft v2",
            "detail": "",
            "status": "completed",
            "due_time": None,
            "links": None,
            "changed_fields": {"status": ["needsAction", "completed"]},
        },
    ]


async def test_update_task_normalizes_wire_empty_sentinels_in_changed_fields(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify 0 vs None timestamps and '' vs None details do not emit false-positive diffs."""
    await load_components("schedule")
    service = component_core.app[SCHEDULE_SERVICE_KEY]

    updated_events: list[ScheduleTaskUpdatedEvent] = []

    async def on_task_updated(event: ScheduleTaskUpdatedEvent) -> None:
        updated_events.append(event)

    component_core.event_bus.subscribe(
        ScheduleTaskUpdatedEvent, on_task_updated, inline=True
    )

    task = await service.create_task(test_user_id, None, "Buy milk")

    # Wire empty sentinels (due_time=0, completed_time=0, detail=None) match initial empty state.
    await service.update_task(
        test_user_id,
        task.task_id,
        due_time=0,
        completed_time=0,
        detail=None,
    )
    assert updated_events == []

    # Setting a real due_time then clearing via wire sentinel 0 records [old, None].
    await service.update_task(test_user_id, task.task_id, due_time=1710000000000)
    await service.update_task(test_user_id, task.task_id, due_time=0)

    assert [ev.changed_fields for ev in updated_events] == [
        {"due_time": [None, 1710000000000]},
        {"due_time": [1710000000000, None]},
    ]
