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
    assert len(groups) >= 1
    assert any(g.task_list_id == group.task_list_id for g in groups)

    # Delete
    deleted = await schedule_service.delete_group(user_id, group.task_list_id)
    assert deleted

    groups_after = await schedule_service.list_groups(user_id)
    assert not any(g.task_list_id == group.task_list_id for g in groups_after)


async def test_task_crud(schedule_service: ScheduleService) -> None:
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
