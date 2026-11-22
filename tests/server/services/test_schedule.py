import asyncio

import pytest

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, ScheduleUpdatedEvent
from supernote.server.services.schedule import ScheduleService


@pytest.fixture
async def schedule_service(session_manager: DatabaseSessionManager) -> ScheduleService:
    """Fixture for the ScheduleService."""
    return ScheduleService(session_manager)


async def test_group_crud(schedule_service: ScheduleService) -> None:
    user_id = 999

    # Create
    group = await schedule_service.create_group(user_id, "Work")
    assert group.task_list_id is not None
    assert group.title == "Work"
    assert group.user_id == user_id

    # List
    groups = await schedule_service.list_groups(user_id)
    assert len(groups) == 1
    assert any(g.task_list_id == group.task_list_id for g in groups)

    # Delete
    deleted = await schedule_service.delete_group(user_id, group.task_list_id)
    assert deleted

    groups_after = await schedule_service.list_groups(user_id)
    assert not any(g.task_list_id == group.task_list_id for g in groups_after)


async def test_group_names_are_not_unique(schedule_service: ScheduleService) -> None:
    """Test that group names are not unique."""
    user_id = 999

    # Create two groups with the same name
    group1 = await schedule_service.create_group(user_id, "Work")
    assert group1.task_list_id is not None
    assert group1.title == "Work"
    assert group1.user_id == user_id

    group2 = await schedule_service.create_group(user_id, "Work")
    assert group2.task_list_id is not None
    assert group2.title == "Work"
    assert group2.user_id == user_id

    # Each group should be unique
    groups = await schedule_service.list_groups(user_id)
    assert len(groups) == 2
    assert [g.title for g in groups] == ["Work", "Work"]

    assert group1.task_list_id != group2.task_list_id

    # Delete the first group
    deleted = await schedule_service.delete_group(user_id, group1.task_list_id)
    assert deleted

    # List groups again
    groups = await schedule_service.list_groups(user_id)
    assert len(groups) == 1
    assert groups[0].task_list_id == group2.task_list_id


async def test_create_group_timestamps(
    schedule_service: ScheduleService,
) -> None:
    """Test group create_time and update_time persistence on creation."""
    user_id = 333
    group = await schedule_service.create_group(
        user_id,
        "Initial Name",
        task_list_id="group_uuid_1",
        create_time_ms=1700000000000,
        last_modified_ms=1700000001000,
    )
    assert group.task_list_id == "group_uuid_1"
    assert group.create_time == 1700000000000
    assert group.update_time == 1700000001000


async def test_update_group_timestamp(
    schedule_service: ScheduleService,
) -> None:
    """Test group update_time persistence on update."""
    user_id = 333
    await schedule_service.create_group(
        user_id,
        "Initial Name",
        task_list_id="group_uuid_2",
        create_time_ms=1700000000000,
        last_modified_ms=1700000001000,
    )

    updated = await schedule_service.update_group(
        user_id, "group_uuid_2", "Renamed Group", last_modified_ms=1700000009000
    )
    assert updated is not None
    assert updated.title == "Renamed Group"
    assert updated.update_time == 1700000009000


async def test_task_crud(schedule_service: ScheduleService) -> None:
    """Test task level operations."""
    user_id = 888
    group = await schedule_service.create_group(user_id, "Inbox")

    # Create Task
    task = await schedule_service.create_task(user_id, group.task_list_id, "Buy Milk")
    assert task.task_id is not None
    assert task.title == "Buy Milk"
    assert task.status == "needsAction"

    # List Tasks
    tasks = await schedule_service.list_tasks(user_id, group.task_list_id)
    assert len(tasks) == 1
    assert tasks[0].task_id == task.task_id

    # Update Task
    updated = await schedule_service.update_task(
        user_id, task.task_id, status="completed", title="Buy Milk & Bread"
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.title == "Buy Milk & Bread"

    # Verify Update in List
    tasks_v2 = await schedule_service.list_tasks(user_id)
    assert tasks_v2[0].title == "Buy Milk & Bread"

    # Delete Task
    deleted = await schedule_service.delete_task(user_id, task.task_id)
    assert deleted

    tasks_v3 = await schedule_service.list_tasks(user_id)
    assert len(tasks_v3) == 0


async def test_isolation(schedule_service: ScheduleService) -> None:
    user1 = 101
    user2 = 102

    g1 = await schedule_service.create_group(user1, "U1 Group")
    g2 = await schedule_service.create_group(user2, "U2 Group")

    # User 1 should only see their group
    l1 = await schedule_service.list_groups(user1)
    assert len(l1) == 1
    assert l1[0].task_list_id == g1.task_list_id

    # User 1 cannot delete User 2 group
    deleted = await schedule_service.delete_group(user1, g2.task_list_id)
    assert not deleted


async def test_shared_client_ids_across_users(
    schedule_service: ScheduleService,
) -> None:
    """Test that different users can use identical client-supplied group and task IDs."""
    user1 = 101
    user2 = 102

    shared_g1 = await schedule_service.create_group(
        user1, "U1 Shared ID", task_list_id="shared-group-id"
    )
    shared_g2 = await schedule_service.create_group(
        user2, "U2 Shared ID", task_list_id="shared-group-id"
    )
    assert shared_g1.task_list_id == shared_g2.task_list_id == "shared-group-id"

    shared_t1 = await schedule_service.create_task(
        user1, "shared-group-id", "U1 Task", task_id="shared-task-id"
    )
    shared_t2 = await schedule_service.create_task(
        user2, "shared-group-id", "U2 Task", task_id="shared-task-id"
    )
    assert shared_t1.task_id == shared_t2.task_id == "shared-task-id"


async def test_delete_group_cascades_contained_tasks(
    schedule_service: ScheduleService,
) -> None:
    """Test that deleting a group automatically cascades and deletes all contained tasks."""
    user_id = 777
    group = await schedule_service.create_group(user_id, "Project X")

    task1 = await schedule_service.create_task(user_id, group.task_list_id, "Subtask 1")
    task2 = await schedule_service.create_task(user_id, group.task_list_id, "Subtask 2")
    assert task1.task_id is not None
    assert task2.task_id is not None

    tasks_before = await schedule_service.list_tasks(user_id, group.task_list_id)
    assert len(tasks_before) == 2

    deleted = await schedule_service.delete_group(user_id, group.task_list_id)
    assert deleted is True

    groups_after = await schedule_service.list_groups(user_id)
    assert not any(g.task_list_id == group.task_list_id for g in groups_after)

    tasks_after = await schedule_service.list_tasks(user_id)
    assert len(tasks_after) == 0


async def test_batch_update_tasks_updates_timestamp_for_since_filter(
    schedule_service: ScheduleService,
) -> None:
    """Test that batch_update_tasks bumps update_time so incremental sync (since) includes updated tasks."""
    user_id = 555
    group = await schedule_service.create_group(user_id, "Reorder Group")
    task1 = await schedule_service.create_task(
        user_id, group.task_list_id, "Task 1", sort=1
    )
    task2 = await schedule_service.create_task(
        user_id, group.task_list_id, "Task 2", sort=2
    )

    sync_token = max(task1.update_time, task2.update_time)
    # The since filter is inclusive; step past the boundary so this test still
    # proves that batch_update_tasks advances update_time.
    assert await schedule_service.list_tasks(user_id, since=sync_token + 1) == []

    await asyncio.sleep(0.005)
    await schedule_service.batch_update_tasks(
        user_id,
        [{"task_id": task1.task_id, "sort": 2, "sort_time": sync_token + 100}],
    )

    updated_task1 = await schedule_service.get_task(user_id, task1.task_id)
    assert updated_task1 is not None
    assert updated_task1.sort == 2
    assert updated_task1.update_time > sync_token
    delta_tasks = await schedule_service.list_tasks(user_id, since=sync_token + 1)
    assert [t.task_id for t in delta_tasks] == [task1.task_id]


async def test_list_tasks_since_includes_tasks_at_cursor(
    schedule_service: ScheduleService,
) -> None:
    """Tasks modified exactly at the since cursor are part of the incremental delta."""
    user_id = 556
    group = await schedule_service.create_group(user_id, "Cursor Group")
    cursor = 1710000001000

    at_update_cursor = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Updated at the cursor",
        last_modified_ms=cursor,
    )
    at_sort_cursor = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Sorted at the cursor",
        last_modified_ms=cursor - 1000,
        sort_time=cursor,
    )
    at_planer_sort_cursor = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Planer-sorted at the cursor",
        last_modified_ms=cursor - 1000,
        planer_sort_time=cursor,
    )
    before_cursor = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Modified before the cursor",
        last_modified_ms=cursor - 1000,
    )

    tasks = await schedule_service.list_tasks(user_id, since=cursor)

    assert {t.task_id for t in tasks} == {
        at_update_cursor.task_id,
        at_sort_cursor.task_id,
        at_planer_sort_cursor.task_id,
    }
    assert before_cursor.task_id not in {t.task_id for t in tasks}


async def test_create_task_completed_time_and_last_modified(
    schedule_service: ScheduleService,
) -> None:
    """Test creating a task with completed_time_ms and last_modified_ms."""
    user_id = 555
    group = await schedule_service.create_group(user_id, "Timestamps Group")
    task = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Done Task",
        status="completed",
        completed_time_ms=1710000000000,
        last_modified_ms=1710000005000,
    )
    assert task.completed_time == 1710000000000
    assert task.update_time == 1710000005000


async def test_create_inbox_task(
    schedule_service: ScheduleService,
) -> None:
    """Test creating an ungrouped Inbox task (group_id=None)."""
    user_id = 444
    inbox_task = await schedule_service.create_task(user_id, None, "Inbox Task 1")
    assert inbox_task.task_list_id is None


async def test_move_task_between_groups_and_inbox(
    schedule_service: ScheduleService,
) -> None:
    """Test moving a task into a custom group and back to Inbox."""
    user_id = 444
    inbox_task = await schedule_service.create_task(user_id, None, "Inbox Task 1")
    group = await schedule_service.create_group(
        user_id,
        "Custom UUID Group",
        task_list_id="group_uuid_abc123",
    )

    moved = await schedule_service.update_task(
        user_id, inbox_task.task_id, task_list_id=group.task_list_id
    )
    assert moved is not None
    assert moved.task_list_id == "group_uuid_abc123"

    await schedule_service.batch_update_tasks(
        user_id,
        [{"task_id": inbox_task.task_id, "task_list_id": None}],
    )
    back_in_inbox = await schedule_service.get_task(user_id, inbox_task.task_id)
    assert back_in_inbox is not None
    assert back_in_inbox.task_list_id is None


async def test_update_and_batch_update_preserve_last_modified_and_clear_nullable_fields(
    schedule_service: ScheduleService,
) -> None:
    """Verify update_task and batch_update_tasks preserve client update_time and clear nullable fields."""
    user_id = 445
    group = await schedule_service.create_group(user_id, "Sync Group")
    task = await schedule_service.create_task(
        user_id,
        group.task_list_id,
        "Task with metadata",
        detail="Initial detail",
        importance="high",
        recurrence="FREQ=DAILY;INTERVAL=1",
        links="eyJhcHBOYW1lIjoiTm90ZSJ9",
        last_modified_ms=1710000001000,
    )
    assert task.update_time == 1710000001000

    # Sort-only batch update preserves existing update_time and still matches since filter via sort_time
    await schedule_service.batch_update_tasks(
        user_id,
        [
            {
                "task_id": task.task_id,
                "sort": 3,
                "sort_time": 1710000005000,
                "update_time": 1710000001000,
            }
        ],
    )
    reordered = await schedule_service.get_task(user_id, task.task_id)
    assert reordered is not None
    assert reordered.sort == 3
    assert reordered.sort_time == 1710000005000
    assert reordered.update_time == 1710000001000
    delta = await schedule_service.list_tasks(user_id, since=1710000002000)
    assert [t.task_id for t in delta] == [task.task_id]

    # Batch update clearing nullable fields and setting explicit update_time
    await schedule_service.batch_update_tasks(
        user_id,
        [
            {
                "task_id": task.task_id,
                "detail": None,
                "importance": None,
                "recurrence": None,
                "links": None,
                "task_list_id": None,
                "update_time": 1710000010000,
            }
        ],
    )
    cleared = await schedule_service.get_task(user_id, task.task_id)
    assert cleared is not None
    assert cleared.detail is None
    assert cleared.importance is None
    assert cleared.recurrence is None
    assert cleared.links is None
    assert cleared.task_list_id is None
    assert cleared.update_time == 1710000010000

    # Single update_task with explicit update_time
    updated_single = await schedule_service.update_task(
        user_id,
        task.task_id,
        title="Updated via single",
        update_time=1710000020000,
    )
    assert updated_single is not None
    assert updated_single.title == "Updated via single"
    assert updated_single.update_time == 1710000020000


async def test_schedule_service_publishes_domain_events_and_skips_noops(
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify ScheduleService publishes ScheduleUpdatedEvent on mutations and skips failed/no-op calls."""
    event_bus = LocalEventBus()
    published: list[ScheduleUpdatedEvent] = []

    async def on_schedule_updated(event: ScheduleUpdatedEvent) -> None:
        published.append(event)

    event_bus.subscribe(ScheduleUpdatedEvent, on_schedule_updated)
    service = ScheduleService(session_manager, event_bus=event_bus)
    user_id = 707

    # Non-existent mutations and empty batch updates must NOT publish events
    assert await service.update_group(user_id, "missing-group", "Title") is None
    assert await service.delete_group(user_id, "missing-group") is False
    assert await service.clear_group_tasks(user_id, "missing-group") is False
    assert await service.update_task(user_id, "missing-task", title="X") is None
    assert await service.delete_task(user_id, "missing-task") is False
    assert await service.batch_update_tasks(user_id, []) is True
    assert await service.batch_update_tasks(user_id, [{"title": "No Task ID"}]) is True
    await asyncio.sleep(0)
    assert published == []

    # Create group -> publishes group event
    group = await service.create_group(user_id, "Event Group")
    await asyncio.sleep(0)
    assert published == [
        ScheduleUpdatedEvent(
            user_id=user_id,
            task_list_id=group.task_list_id,
            task_id=None,
            equipment_no=None,
        )
    ]
    published.clear()

    # Clearing an already-empty group is a no-op -> does NOT publish
    assert await service.clear_group_tasks(user_id, group.task_list_id) is False
    await asyncio.sleep(0)
    assert published == []

    # Create task -> publishes task event
    task = await service.create_task(user_id, group.task_list_id, "Task A")
    await asyncio.sleep(0)
    assert published == [
        ScheduleUpdatedEvent(
            user_id=user_id,
            task_list_id=group.task_list_id,
            task_id=task.task_id,
            equipment_no=None,
        )
    ]
    published.clear()

    # Batch update with no allowed fields is a no-op -> does NOT publish
    assert (
        await service.batch_update_tasks(
            user_id, [{"task_id": task.task_id, "unknown_field": "x"}]
        )
        is True
    )
    await asyncio.sleep(0)
    assert published == []

    # Clearing a non-empty group -> publishes group event
    assert await service.clear_group_tasks(user_id, group.task_list_id) is True
    await asyncio.sleep(0)
    assert published == [
        ScheduleUpdatedEvent(
            user_id=user_id,
            task_list_id=group.task_list_id,
            task_id=None,
            equipment_no=None,
        )
    ]
