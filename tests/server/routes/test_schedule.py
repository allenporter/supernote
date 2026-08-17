import asyncio

import pytest
from aiohttp.test_utils import TestClient
from ical.calendar_stream import IcsCalendarStream

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.models.base import BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ScheduleTaskGroupItem,
    ScheduleTaskLinkDTO,
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

    base_url = str(client.make_url(""))
    return Client(client.session, auth=TokenAuth(), host=base_url)


async def test_schedule_flow(authenticated_client: Client) -> None:
    schedule = ScheduleClient(authenticated_client)

    # Create Group
    group_vo = await schedule.create_group("My Projects")
    assert isinstance(group_vo, AddScheduleTaskGroupVO)
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # List Groups
    groups = [g async for g in schedule.list_groups()]
    assert len(groups) == 1
    my_group = next((g for g in groups if str(g.task_list_id) == str(group_id)), None)
    assert my_group is not None
    assert my_group.title == "My Projects"
    assert isinstance(my_group, ScheduleTaskGroupItem)

    # Create Task
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

    # List Tasks
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks) == 1
    task = tasks[0]
    assert str(task.task_id) == str(task_id)
    assert str(task.task_list_id) == str(group_id)
    assert task.title == "Finish Refactor"
    assert task.is_reminder_on == BooleanEnum.NO

    # Update Task
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

    # Delete Task
    await schedule.delete_task(task_id)
    tasks_after_delete = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks_after_delete) == 0

    # Delete Group
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

    await schedule.update_task(task_id, title="Updated Title")
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].title == "Updated Title"
    assert tasks[0].detail == "Original Detail"
    assert tasks[0].due_time == 1000

    await schedule.update_task(task_id, title="Updated Title", detail="Updated Detail")
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].title == "Updated Title"
    assert tasks[0].detail == "Updated Detail"

    await schedule.update_task(task_id, title="Updated Title", due_time=0)
    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].due_time == 0

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


async def test_update_task_partial_payload(authenticated_client: Client) -> None:
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Partial Update Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task_vo = await schedule.create_task(group_id, "Original Title")
    assert task_vo.task_id is not None

    # Perform raw PUT request omitting lastModified and title
    resp = await authenticated_client.put(
        "/api/file/schedule/task",
        json={"taskId": task_vo.task_id, "status": "completed"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    tasks = [t async for t in schedule.list_tasks(group_id)]
    assert tasks[0].status == "completed"
    assert tasks[0].title == "Original Title"

    await schedule.delete_group(group_id)


async def test_task_links_and_sort_fields_persistence(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Links Test Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    link_dto = ScheduleTaskLinkDTO(
        app_name="Note",
        path="/Note/Planner.note",
        page=5,
    )
    sample_links = link_dto.to_b64()
    create_vo = await schedule.create_task(
        group_id,
        "Linked Notebook Event",
        links=sample_links,
        planer_sort=42,
    )
    assert create_vo.success is True
    assert create_vo.task_id is not None
    task_id = int(create_vo.task_id)

    task_detail = await schedule.get_task(task_id)
    assert task_detail.success is True
    assert task_detail.links == sample_links
    assert task_detail.planer_sort == 42

    await schedule.delete_group(group_id)


async def test_task_notebook_links_encoding_and_decoding(
    authenticated_client: Client,
) -> None:
    """Dedicated test verifying Base64 JSON notebook links round-trip persistence."""
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Notebook Links Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # Construct explicit Supernote notebook link using ScheduleTaskLinkDTO
    link_dto = ScheduleTaskLinkDTO(
        app_name="Note",
        file_id="739213260577833138",
        path="/Note/2026_Executive_Planner.note",
        page=24,
        page_id="p24_guid_9823749823",
    )
    encoded_links = link_dto.to_b64()

    # Create task with encoded notebook link
    create_vo = await schedule.create_task(
        group_id,
        "Quarterly Planning Meeting",
        detail="Action item created from page 24 of Executive Planner",
        importance="high",
        links=encoded_links,
    )
    assert create_vo.success is True
    assert create_vo.task_id is not None
    task_id = int(create_vo.task_id)

    # Verify GET task returns exact links string and decodes using ScheduleTaskLinkDTO.from_b64
    task_detail = await schedule.get_task(task_id)
    assert task_detail.success is True
    assert task_detail.links == encoded_links

    assert task_detail.links is not None
    decoded_dto = ScheduleTaskLinkDTO.from_b64(task_detail.links)
    assert decoded_dto == link_dto
    assert decoded_dto.app_name == "Note"
    assert decoded_dto.path == "/Note/2026_Executive_Planner.note"
    assert decoded_dto.page == 24
    assert decoded_dto.file_id == "739213260577833138"
    assert decoded_dto.page_id == "p24_guid_9823749823"

    await schedule.delete_group(group_id)


async def test_schedule_group_and_task_routes(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)

    # Create Group
    group_vo = await schedule.create_group("Group Alpha")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # Get Group Details
    group_detail = await schedule.get_group(group_id)
    assert group_detail.success is True
    assert group_detail.title == "Group Alpha"
    assert str(group_detail.task_list_id) == str(group_id)

    # Update Group Title
    up_res = await schedule.update_group(group_id, "Group Alpha Updated")
    assert up_res.success is True
    group_detail_up = await schedule.get_group(group_id)
    assert group_detail_up.title == "Group Alpha Updated"

    # Create Task & Get Task
    task_vo = await schedule.create_task(group_id, "Task Beta", detail="Beta detail")
    assert task_vo.task_id is not None
    task_id = int(task_vo.task_id)

    task_detail = await schedule.get_task(task_id)
    assert task_detail.success is True
    assert task_detail.title == "Task Beta"
    assert task_detail.detail == "Beta detail"

    # Clear Group Tasks
    clear_res = await schedule.clear_group(group_id)
    assert clear_res.success is True

    tasks_after_clear = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks_after_clear) == 0

    await schedule.delete_group(group_id)


async def test_sort_endpoints_return_200(authenticated_client: Client) -> None:
    res_post = await authenticated_client.request(
        "post", "/api/file/schedule/sort", json={}
    )
    assert res_post.status == 200

    res_put = await authenticated_client.request(
        "put", "/api/file/schedule/sort", json={}
    )
    assert res_put.status == 200

    res_del = await authenticated_client.request(
        "delete", "/api/file/schedule/sort/123"
    )
    assert res_del.status == 200

    res_query = await authenticated_client.request(
        "post", "/api/file/query/schedule/sort", json={}
    )
    assert res_query.status == 200


async def test_batch_update_task_list_transactional_rollback(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)

    group_vo = await schedule.create_group("Batch Test Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task1_vo = await schedule.create_task(group_id, "Task 1", detail="Detail 1")
    task2_vo = await schedule.create_task(group_id, "Task 2", detail="Detail 2")
    assert task1_vo.task_id is not None
    assert task2_vo.task_id is not None

    task1_id = int(task1_vo.task_id)
    task2_id = int(task2_vo.task_id)

    # Batch update where Task 1 is valid, but Task 2 exceeds MAX_TITLE_LENGTH
    invalid_title = "A" * 300
    batch_payload = {
        "taskListId": str(group_id),
        "updateScheduleTaskList": [
            {
                "taskId": str(task1_id),
                "title": "Task 1 Updated",
                "lastModified": 1000,
            },
            {
                "taskId": str(task2_id),
                "title": invalid_title,
                "lastModified": 1000,
            },
        ],
    }

    res = await authenticated_client.request(
        "put", "/api/file/schedule/task/list", json=batch_payload
    )
    assert res.status == 400

    # Verify Task 1 was NOT updated due to atomic rollback
    task1_detail = await schedule.get_task(task1_id)
    assert task1_detail.title == "Task 1"

    task2_detail = await schedule.get_task(task2_id)
    assert task2_detail.title == "Task 2"

    await schedule.delete_group(group_id)


async def test_list_tasks_filtering_by_group_id(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)

    group_a_vo = await schedule.create_group("Group A")
    group_b_vo = await schedule.create_group("Group B")
    assert group_a_vo.task_list_id is not None
    assert group_b_vo.task_list_id is not None
    group_a_id = int(group_a_vo.task_list_id)
    group_b_id = int(group_b_vo.task_list_id)

    task_a_vo = await schedule.create_task(group_a_id, "Task in Group A")
    task_b_vo = await schedule.create_task(group_b_id, "Task in Group B")
    assert task_a_vo.task_id is not None
    assert task_b_vo.task_id is not None

    # Filter by Group A
    tasks_a = [t async for t in schedule.list_tasks(group_a_id)]
    assert len(tasks_a) == 1
    assert tasks_a[0].title == "Task in Group A"

    # Filter by Group B
    tasks_b = [t async for t in schedule.list_tasks(group_b_id)]
    assert len(tasks_b) == 1
    assert tasks_b[0].title == "Task in Group B"

    # List all without group filter
    all_tasks = [t async for t in schedule.list_tasks(group_id=None)]
    assert len(all_tasks) == 2
    titles = {t.title for t in all_tasks}
    assert titles == {"Task in Group A", "Task in Group B"}

    # Cleanup
    await schedule.delete_group(group_a_id)
    await schedule.delete_group(group_b_id)


async def test_delete_group_cascades_contained_tasks(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)

    group_vo = await schedule.create_group("Cascade Route Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task1_vo = await schedule.create_task(group_id, "Subtask 1")
    task2_vo = await schedule.create_task(group_id, "Subtask 2")
    assert task1_vo.task_id is not None
    assert task2_vo.task_id is not None

    tasks_before = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks_before) == 2

    await schedule.delete_group(group_id)

    tasks_after = [t async for t in schedule.list_tasks(group_id)]
    assert len(tasks_after) == 0


async def test_batch_update_task_list_sort_fields(
    authenticated_client: Client,
) -> None:
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Sort Batch Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task1_vo = await schedule.create_task(group_id, "Task 101")
    task2_vo = await schedule.create_task(group_id, "Task 102")
    assert task1_vo.task_id is not None
    assert task2_vo.task_id is not None

    # Perform batch update of sort indexes (simulating device drag-and-drop reorder)
    resp = await authenticated_client.put(
        "/api/file/schedule/task/list",
        json={
            "updateScheduleTaskList": [
                {
                    "taskId": task1_vo.task_id,
                    "sort": 1,
                    "planerSort": 10,
                    "allSort": 100,
                },
                {
                    "taskId": task2_vo.task_id,
                    "sort": 2,
                    "planerSort": 20,
                    "allSort": 200,
                },
            ]
        },
    )
    assert resp.status == 200
    res_data = await resp.json()
    assert res_data["success"] is True

    # Verify task 1 sort fields
    t1_res = await authenticated_client.get(
        f"/api/file/schedule/task/{task1_vo.task_id}"
    )
    t1_data = await t1_res.json()
    assert t1_data["sort"] == 1
    assert t1_data["planerSort"] == 10
    assert t1_data["allSort"] == 100

    # Verify task 2 sort fields
    t2_res = await authenticated_client.get(
        f"/api/file/schedule/task/{task2_vo.task_id}"
    )
    t2_data = await t2_res.json()
    assert t2_data["sort"] == 2
    assert t2_data["planerSort"] == 20
    assert t2_data["allSort"] == 200

    await schedule.delete_group(group_id)


async def test_create_task_with_client_generated_id_and_server_fallback(
    authenticated_client: Client,
) -> None:
    """Test task creation with client-provided taskId and server autoincrement fallback."""
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("ID Test Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # Client-provided taskId (offline Supernote device sync)
    client_custom_id = "9876543210"
    create_vo = await schedule.create_task(
        group_id,
        "Offline Created Task",
        task_id=client_custom_id,
    )
    assert create_vo.success is True
    assert create_vo.task_id == client_custom_id

    # Verify task is stored under the exact client-generated taskId in DB
    task_vo = await schedule.get_task(int(client_custom_id))
    assert task_vo.success is True
    assert str(task_vo.task_id) == client_custom_id
    assert task_vo.title == "Offline Created Task"

    # Server-generated taskId fallback (when taskId omitted)
    server_vo = await schedule.create_task(group_id, "Web UI Created Task")
    assert server_vo.success is True
    server_task_id = server_vo.task_id
    assert server_task_id is not None
    assert server_task_id != client_custom_id

    server_task = await schedule.get_task(int(server_task_id))
    assert server_task.success is True
    assert server_task.title == "Web UI Created Task"

    await schedule.delete_group(group_id)


async def test_schedule_delta_sync_flow(authenticated_client: Client) -> None:
    """Test delta sync flow using nextSyncToken via ScheduleClient."""
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Delta Sync Group")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    # Create initial tasks
    t1_vo = await schedule.create_task(group_id, "Task 1 Initial")
    t2_vo = await schedule.create_task(group_id, "Task 2 Initial")
    assert t1_vo.task_id is not None
    assert t2_vo.task_id is not None

    # Query with no sync token -> get both tasks back & nextSyncToken via ScheduleClient
    initial_vo = await schedule.get_tasks_all(group_id=group_id)
    assert initial_vo.success is True
    initial_tasks = initial_vo.schedule_task
    assert len(initial_tasks) == 2
    sync_token = initial_vo.next_sync_token
    assert sync_token is not None

    # Ensure timestamp progression
    await asyncio.sleep(0.02)

    # Update 1 task, add 1 task
    await schedule.update_task(int(t1_vo.task_id), title="Task 1 Updated")
    t3_vo = await schedule.create_task(group_id, "Task 3 New")
    assert t3_vo.task_id is not None

    # Query back with nextSyncToken -> get updated task & new task (2 tasks)
    delta_vo = await schedule.get_tasks_all(
        group_id=group_id, next_sync_token=sync_token
    )
    assert delta_vo.success is True
    delta_tasks = delta_vo.schedule_task
    sync_token2 = delta_vo.next_sync_token
    assert sync_token2 is not None
    assert sync_token2 >= sync_token

    delta_task_ids = {t.task_id for t in delta_tasks}
    assert t1_vo.task_id in delta_task_ids
    assert t3_vo.task_id in delta_task_ids
    assert t2_vo.task_id not in delta_task_ids

    updated_t1 = next(t for t in delta_tasks if t.task_id == t1_vo.task_id)
    assert updated_t1.title == "Task 1 Updated"

    # Query again with sync_token2 -> no new changes (0 tasks), nextSyncToken propagated back
    delta_vo2 = await schedule.get_tasks_all(
        group_id=group_id, next_sync_token=sync_token2
    )
    assert delta_vo2.success is True
    assert len(delta_vo2.schedule_task) == 0
    sync_token3 = delta_vo2.next_sync_token
    assert sync_token3 is not None
    assert sync_token3 >= sync_token2

    await schedule.delete_group(group_id)


async def test_ical_feed_unauthorized(client: TestClient) -> None:
    """Test GET /api/schedule/feed.ics without authentication returns 401."""
    resp = await client.get("/api/schedule/feed.ics")
    assert resp.status == 401


async def test_ical_feed_auth_via_header(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /api/schedule/feed.ics with header authentication."""
    resp = await client.get("/api/schedule/feed.ics", headers=auth_headers)
    assert resp.status == 200
    assert "text/calendar" in resp.headers["Content-Type"]
    assert "inline; filename=" in resp.headers.get("Content-Disposition", "")

    body = await resp.text()
    assert body.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in body


async def test_ical_feed_content_and_filtering(
    client: TestClient,
    authenticated_client: Client,
    auth_headers: dict[str, str],
) -> None:
    """Test creating tasks via ScheduleClient and retrieving feed via HTTP GET."""
    schedule = ScheduleClient(authenticated_client)

    # Populate data via ScheduleClient
    group_vo = await schedule.create_group("Sprint Tasks")
    assert group_vo.task_list_id is not None
    group_id = int(group_vo.task_list_id)

    task1 = await schedule.create_task(
        group_id,
        "Implement ICS Route",
        detail="Add feed.ics endpoint in schedule routes",
    )
    assert task1.task_id is not None

    # Query ICS feed via ScheduleClient SDK
    ics_content = await schedule.get_ical_feed()
    calendar = IcsCalendarStream.calendar_from_ics(ics_content)
    assert calendar is not None
    assert len(calendar.todos) >= 1

    todo = next(t for t in calendar.todos if t.summary == "Implement ICS Route")
    assert todo.description == "Add feed.ics endpoint in schedule routes"

    # Filter by taskListId query param via ScheduleClient SDK
    filtered_content = await schedule.get_ical_feed(group_id=group_id)
    filtered_calendar = IcsCalendarStream.calendar_from_ics(filtered_content)
    assert len(filtered_calendar.todos) == 1

    # Cleanup
    await schedule.delete_group(group_id)


async def test_schedule_string_uuid_support(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify that non-digit string UUIDs (e.g. Partner App hex IDs) do not cause int() parsing errors."""
    hex_list_id = "dcf35927c2c7279e3d204f592af6e9ed"
    hex_task_id = "a1b2c3d4e5f67890123456789abcdef0"

    # 1. Query all tasks with hex taskListId
    resp = await client.post(
        "/api/file/schedule/task/all",
        json={"taskListId": hex_list_id},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # 2. Add task with hex taskListId & hex taskId
    resp = await client.post(
        "/api/file/schedule/task",
        json={
            "taskListId": hex_list_id,
            "taskId": hex_task_id,
            "title": "Partner App Task",
            "detail": "Testing string UUID support",
        },
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    created_task_id = data["taskId"]

    # 3. Query created task with string taskId
    resp = await client.get(
        f"/api/file/schedule/task/{created_task_id}",
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["title"] == "Partner App Task"

