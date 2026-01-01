import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.models.base import BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ScheduleTaskGroupItem,
    UpdateScheduleTaskVO,
)


@pytest.fixture
async def authenticated_client(
    client: TestClient,  # From server conftest
    auth_headers: dict[str, str],  # From server conftest
) -> Client:
    token = auth_headers["x-access-token"]

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    # client is TestClient, client.session is ClientSession
    base_url = str(client.make_url(""))
    return Client(client.session, auth=TokenAuth(), host=base_url)


async def test_schedule_flow(authenticated_client: Client) -> None:
    schedule = ScheduleClient(authenticated_client)

    # 1. Create Group
    group_vo = await schedule.create_group("My Projects")
    assert isinstance(group_vo, AddScheduleTaskGroupVO)
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # 2. List Groups
    groups = [g async for g in schedule.list_groups()]
    assert len(groups) == 1
    # Find our group
    my_group = next((g for g in groups if str(g.task_list_id) == str(group_id)), None)
    assert my_group is not None
    assert my_group.title == "My Projects"
    assert isinstance(my_group, ScheduleTaskGroupItem)

    # 3. Create Task
    task_vo = await schedule.create_task(
        group_id,
        "Finish Refactor",
        detail="Must use VFS",
        status="needsAction",
        importance="high",
    )
    assert isinstance(task_vo, AddScheduleTaskVO)
    assert task_vo.task_id is not None
    task_id = int(task_vo.task_id)

    # 4. List Tasks
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks) == 1
    task = tasks[0]
    assert str(task.task_id) == str(task_id)
    assert str(task.task_list_id) == str(group_id)
    assert task.title == "Finish Refactor"
    assert task.is_reminder_on == BooleanEnum.NO  # Response is BooleanEnum

    # 5. Update Task
    update_vo = await schedule.update_task(
        task_id, title="Finish Refactor", status="completed", is_reminder_on=True
    )
    assert isinstance(update_vo, UpdateScheduleTaskVO)
    assert str(update_vo.task_id) == str(task_id)

    # Verify update
    tasks_after = [t async for t in schedule.list_tasks(group_id)]
    updated_task = tasks_after[0]
    assert updated_task.status == "completed"
    assert updated_task.is_reminder_on == BooleanEnum.YES

    # 6. Delete Task
    await schedule.delete_task(task_id)
    tasks_after_delete = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks_after_delete) == 0

    # 7. Delete Group
    await schedule.delete_group(group_id)
    groups_after = [g async for g in schedule.list_groups()]
    assert len(groups_after) == 0


async def test_update_task_fields(authenticated_client: Client) -> None:
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Update Test Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task_vo = await schedule.create_task(
        group_id, "Original Title", detail="Original Detail", due_time=1000
    )
    assert task_vo.task_id is not None
    task_id = int(task_vo.task_id)

    # Test 1: Partial Update - Title Only
    await schedule.update_task(task_id, title="Updated Title")
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].title == "Updated Title"
    assert tasks[0].detail == "Original Detail"  # Should be unchanged
    assert tasks[0].due_time == 1000  # Should be unchanged

    # Test 2: Update Detail (Title required)
    await schedule.update_task(task_id, title="Updated Title", detail="Updated Detail")
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].title == "Updated Title"  # Should be unchanged
    assert tasks[0].detail == "Updated Detail"

    # Test 3: Update Numeric Field (Zero handling?)
    # due_time = 0
    await schedule.update_task(task_id, title="Updated Title", due_time=0)
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].due_time == 0

    # Test 4: Update All Fields
    await schedule.update_task(
        task_id,
        title="Final Title",
        detail="Final Detail",
        status="completed",
        importance="low",
        due_time=9999,
        is_reminder_on=True,
    )
    tasks = [t async for t in schedule.list_tasks(group_id)]
    t = tasks[0]
    assert t.title == "Final Title"
    assert t.detail == "Final Detail"
    assert t.status == "completed"
    assert t.importance == "low"
    assert t.due_time == 9999
    assert t.is_reminder_on == BooleanEnum.YES

    # Cleanup
    await schedule.delete_group(group_id)
