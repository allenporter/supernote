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


async def test_create_task_ungrouped(schedule_service: ScheduleService) -> None:
    """The CLI can create an ungrouped task (no group_id), matching the device shape."""
    user_id = 606
    task = await schedule_service.create_task(user_id, None, "Loose task")
    assert task.task_id is not None
    assert task.task_list_id is None
    assert task.title == "Loose task"

    # It's listed account-wide (the device's ungrouped read).
    tasks = await schedule_service.list_tasks(user_id)
    assert [(t.title, t.task_list_id) for t in tasks] == [("Loose task", None)]


async def test_upsert_task_device_shape_round_trips(
    schedule_service: ScheduleService,
) -> None:
    """A device-shaped task (string id, ungrouped, rich fields) persists faithfully."""
    user_id = 777
    task = await schedule_service.upsert_task(
        user_id,
        device_task_id="e704336260dcb1d775a2ebbad1fd6491",
        title="Make overnight oats",
        status="completed",
        completed_time=1740606681928,
        due_time=1740606876842,
        last_modified=1740606876843,
        links="eyJhcHBOYW1lIjoibm90ZSJ9",
        sort=0,
        sort_completed=2,
        planer_sort=0,
        planer_sort_time=1740606876843,
        sort_time=1743954561808,
    )

    # Surrogate PK is generated; the device id lives alongside it, ungrouped.
    assert task.task_id is not None
    assert task.device_task_id == "e704336260dcb1d775a2ebbad1fd6491"
    assert task.task_list_id is None
    assert task.is_deleted is False

    # Re-read faithfully.
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.device_task_id == "e704336260dcb1d775a2ebbad1fd6491"
    assert t.title == "Make overnight oats"
    assert t.status == "completed"
    assert t.completed_time == 1740606681928
    assert t.last_modified == 1740606876843
    assert t.links == "eyJhcHBOYW1lIjoibm90ZSJ9"
    assert t.sort == 0
    assert t.sort_completed == 2
    assert t.planer_sort == 0
    assert t.sort_time == 1743954561808


async def test_upsert_task_updates_not_duplicates(
    schedule_service: ScheduleService,
) -> None:
    """Re-pushing the same device task id upserts the existing row."""
    user_id = 777
    device_id = "abc123abc123abc123abc123abc12300"

    await schedule_service.upsert_task(
        user_id, device_task_id=device_id, title="First", status="needsAction"
    )
    await schedule_service.upsert_task(
        user_id, device_task_id=device_id, title="Edited", status="completed"
    )

    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert tasks[0].title == "Edited"
    assert tasks[0].status == "completed"


async def test_upsert_task_delete_tombstones(
    schedule_service: ScheduleService,
) -> None:
    """A device delete (is_deleted=True) tombstones; the task drops from the read."""
    user_id = 777
    device_id = "def456def456def456def456def45600"

    await schedule_service.upsert_task(
        user_id, device_task_id=device_id, title="Doomed"
    )
    assert len(await schedule_service.list_tasks(user_id)) == 1

    await schedule_service.upsert_task(
        user_id, device_task_id=device_id, title="Doomed", is_deleted=True
    )
    # Default read hides tombstones (deletion reflected as absence next sync)...
    assert await schedule_service.list_tasks(user_id) == []
    # ...but the tombstone row is retained.
    with_deleted = await schedule_service.list_tasks(user_id, include_deleted=True)
    assert len(with_deleted) == 1
    assert with_deleted[0].is_deleted is True


async def test_upsert_task_isolation(schedule_service: ScheduleService) -> None:
    """The same device task id under two users are distinct rows (unique per user)."""
    device_id = "0000000000000000000000000000ffff"
    await schedule_service.upsert_task(201, device_task_id=device_id, title="U1")
    await schedule_service.upsert_task(202, device_task_id=device_id, title="U2")

    u1 = await schedule_service.list_tasks(201)
    u2 = await schedule_service.list_tasks(202)
    assert [t.title for t in u1] == ["U1"]
    assert [t.title for t in u2] == ["U2"]


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
