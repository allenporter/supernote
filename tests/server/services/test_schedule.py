import asyncio

import pytest

from supernote.server.db.session import DatabaseSessionManager
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
    assert await schedule_service.list_tasks(user_id, since=sync_token) == []

    await asyncio.sleep(0.005)
    await schedule_service.batch_update_tasks(
        user_id,
        [{"task_id": task1.task_id, "sort": 2, "sort_time": sync_token + 100}],
    )

    updated_task1 = await schedule_service.get_task(user_id, task1.task_id)
    assert updated_task1 is not None
    assert updated_task1.sort == 2
    assert updated_task1.update_time > sync_token
    delta_tasks = await schedule_service.list_tasks(user_id, since=sync_token)
    assert [t.task_id for t in delta_tasks] == [task1.task_id]


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


async def test_delete_user_data_isolates_tenants(
    schedule_service: ScheduleService,
) -> None:
    """Verify delete_user_data purges all groups and tasks for target user only."""
    u1_group = await schedule_service.create_group(101, "U1 Group")
    await schedule_service.create_task(101, u1_group.task_list_id, "U1 Task")
    await schedule_service.create_task(101, None, "U1 Inbox")

    u2_group = await schedule_service.create_group(202, "U2 Group")
    await schedule_service.create_task(202, u2_group.task_list_id, "U2 Task")

    await schedule_service.delete_user_data(101)

    assert await schedule_service.list_groups(101) == []
    assert await schedule_service.list_tasks(101) == []
    assert len(await schedule_service.list_groups(202)) == 1
    assert len(await schedule_service.list_tasks(202)) == 1
