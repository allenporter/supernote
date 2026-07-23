import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.models.base import BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ScheduleTaskAllVO,
    ScheduleTaskGroupItem,
    ScheduleTaskGroupVO,
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


async def test_cli_create_ungrouped_task_appears_on_device(
    client: TestClient,
    auth_headers: dict[str, str],
    authenticated_client: Client,
) -> None:
    """A CLI task created with no group persists ungrouped and shows in device task/all.

    Parity fix (ticket 06): the CLI used to require a group, so a CLI-authored task
    couldn't match the device's ungrouped shape. Creating one with no taskListId now
    succeeds and appears account-wide like a device task.
    """
    # CLI create with no group via the bespoke route.
    resp = await client.post(
        "/api/schedule/tasks",
        headers=auth_headers,
        json={"title": "Ungrouped CLI task"},
    )
    assert resp.status == 200
    vo = AddScheduleTaskVO.from_dict(await resp.json())
    assert vo.success is True
    assert vo.task_id is not None

    # It surfaces in the device's account-wide task/all, ungrouped.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert len(all_vo.schedule_task) == 1
    t = all_vo.schedule_task[0]
    assert t.title == "Ungrouped CLI task"
    assert t.task_list_id is None


async def test_cli_delete_reaches_device_as_tombstone(
    client: TestClient,
    auth_headers: dict[str, str],
    authenticated_client: Client,
) -> None:
    """A CLI-deleted task reaches the device as an isDeleted='Y' tombstone (no resurrection).

    The device sync is a last-writer merge: if a delete performed off-device (here via the
    CLI) is simply *omitted* from the device's task/all, the device reads it as "unchanged"
    and re-pushes its copy, resurrecting the task. So the device read must surface the
    tombstone — while the CLI's own read stays live-only.
    """
    # CLI creates then deletes a task.
    resp = await client.post(
        "/api/schedule/tasks", headers=auth_headers, json={"title": "Doomed"}
    )
    assert resp.status == 200
    task_id = AddScheduleTaskVO.from_dict(await resp.json()).task_id
    assert task_id is not None

    del_resp = await client.delete(
        f"/api/schedule/tasks/{task_id}", headers=auth_headers
    )
    assert del_resp.status == 200

    # Device task/all surfaces the tombstone so the device drops its local copy.
    device_resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    device_vo = ScheduleTaskAllVO.from_dict(await device_resp.json())
    assert len(device_vo.schedule_task) == 1
    tombstone = device_vo.schedule_task[0]
    assert tombstone.task_id == task_id
    assert tombstone.is_deleted == BooleanEnum.YES
    assert tombstone.last_modified is not None

    # The CLI's own read is live-only — the task is gone from its perspective.
    cli_resp = await client.get("/api/schedule/tasks", headers=auth_headers)
    cli_vo = ScheduleTaskAllVO.from_dict(await cli_resp.json())
    assert cli_vo.schedule_task == []


async def test_device_delete_ack_purges_and_converges(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The device acks a task tombstone via DELETE /api/file/schedule/task/{id}.

    Live regression (ticket 08): after task/all handed back an isDeleted='Y' tombstone, the
    device confirmed the deletion by DELETEing the task by its device id — an unregistered
    route that 404'd and surfaced as "To-do Sync failed" even though the delete had
    succeeded. The route now purges the tombstone and returns 200. Purging is what makes the
    protocol *converge*: task/all stops re-serving the row, so the device stops re-acking it
    (retaining it makes the device DELETE the same row every sync forever — live-observed).
    """
    device_task_id = DEVICE_TASK_PUSH["taskId"]
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )
    # Delete elsewhere → tombstone; task/all surfaces it (the device sees isDeleted='Y').
    await client.post(
        "/api/file/schedule/task",
        headers=auth_headers,
        json={**DEVICE_TASK_PUSH, "isDeleted": "Y"},
    )

    # The device acknowledges by DELETEing the task by its own string id.
    ack = await client.delete(
        f"/api/file/schedule/task/{device_task_id}", headers=auth_headers
    )
    assert ack.status == 200
    assert (await ack.json())["success"] is True

    # Converged: the tombstone is purged, so task/all no longer re-serves it.
    resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    assert ScheduleTaskAllVO.from_dict(await resp.json()).schedule_task == []

    # Idempotent: a repeated ack for the now-gone task still returns 200 (no banner).
    ack2 = await client.delete(
        f"/api/file/schedule/task/{device_task_id}", headers=auth_headers
    )
    assert ack2.status == 200


async def test_cli_delete_ack_by_surrogate_id_purges(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The device acks a CLI-deleted tombstone by its surrogate id, and it purges.

    A CLI-created task has no device_task_id, so task/all echoes its surrogate task_id as
    the id string. When the device acks that tombstone it DELETEs by *that* id — not a
    device id. The purge must resolve it (finding: an ack keyed only on device_task_id
    silently misses CLI rows, leaving the tombstone re-served and re-acked forever).
    """
    resp = await client.post(
        "/api/schedule/tasks", headers=auth_headers, json={"title": "Doomed"}
    )
    task_id = AddScheduleTaskVO.from_dict(await resp.json()).task_id
    assert task_id is not None
    await client.delete(f"/api/schedule/tasks/{task_id}", headers=auth_headers)

    # task/all echoes the tombstone under the surrogate id (no device_task_id to use).
    device_resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    tombstone = ScheduleTaskAllVO.from_dict(await device_resp.json()).schedule_task[0]
    assert tombstone.task_id == task_id

    # The device acks by that surrogate id string → 200, and the row is purged.
    ack = await client.delete(
        f"/api/file/schedule/task/{tombstone.task_id}", headers=auth_headers
    )
    assert ack.status == 200
    assert (await ack.json())["success"] is True

    # Converged: task/all no longer re-serves the CLI tombstone.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    assert ScheduleTaskAllVO.from_dict(await resp2.json()).schedule_task == []


async def test_device_group_all_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
    authenticated_client: Client,
) -> None:
    """The device pulls its planner groups via POST /api/file/schedule/group/all.

    Regression: the server only registered the bespoke GET /api/schedule/groups, so
    the device's spec call to /api/file/schedule/group/all returned 404, which the
    firmware surfaces as "private cloud sync failed". This asserts the spec route is
    registered and returns the groups.
    """
    # Seed a group via the bespoke API the CLI uses.
    schedule = ScheduleClient(authenticated_client)
    group_vo = await schedule.create_group("Planner")
    assert group_vo.task_list_id is not None

    # Hit the spec route the device uses (POST, ScheduleTaskGroupDTO body).
    resp = await client.post(
        "/api/file/schedule/group/all",
        headers=auth_headers,
        json={"maxResults": "100", "pageToken": None},
    )

    assert resp.status == 200
    vo = ScheduleTaskGroupVO.from_dict(await resp.json())
    assert vo.success is True
    assert [g.title for g in vo.schedule_task_group] == ["Planner"]
    assert isinstance(vo.schedule_task_group[0], ScheduleTaskGroupItem)


async def test_device_group_all_endpoint_empty(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The device's group/all call returns 200 with an empty list when no groups exist.

    The device sends this on every sync; it must not 404 even before any planner data
    is created.
    """
    resp = await client.post(
        "/api/file/schedule/group/all",
        headers=auth_headers,
        json={},
    )

    assert resp.status == 200
    vo = ScheduleTaskGroupVO.from_dict(await resp.json())
    assert vo.success is True
    assert vo.schedule_task_group == []


async def test_device_task_all_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
    authenticated_client: Client,
) -> None:
    """The device pulls all planner tasks via POST /api/file/schedule/task/all.

    Companion to group/all: the live device sync calls task/all immediately after
    group/all, and while unregistered it 404'd, keeping "private cloud sync failed"
    even after group/all was fixed. This also guards that the endpoint is
    account-wide (tasks across ALL groups), not group-scoped like the bespoke route.
    """
    schedule = ScheduleClient(authenticated_client)
    g1 = await schedule.create_group("Work")
    g2 = await schedule.create_group("Home")
    assert g1.task_list_id is not None and g2.task_list_id is not None
    await schedule.create_task(int(g1.task_list_id), "Ship task/all")
    await schedule.create_task(int(g2.task_list_id), "Buy milk")

    resp = await client.post(
        "/api/file/schedule/task/all",
        headers=auth_headers,
        json={"maxResults": "100"},
    )

    assert resp.status == 200
    vo = ScheduleTaskAllVO.from_dict(await resp.json())
    assert vo.success is True
    # Tasks from BOTH groups are returned (account-wide, not group-scoped).
    assert sorted(t.title for t in vo.schedule_task) == ["Buy milk", "Ship task/all"]


async def test_device_task_all_endpoint_empty(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """task/all returns 200 with an empty list when no tasks exist.

    The device sends this on every sync, right after group/all; it must not 404.
    """
    resp = await client.post(
        "/api/file/schedule/task/all",
        headers=auth_headers,
        json={},
    )

    assert resp.status == 200
    vo = ScheduleTaskAllVO.from_dict(await resp.json())
    assert vo.success is True
    assert vo.schedule_task == []


# The exact body a live device pushed to POST /api/file/schedule/task (captured in
# .scratch/sync-down-diagnosis/assets/14-post-sync-trace.log, which 404'd on HEAD).
DEVICE_TASK_PUSH = {
    "taskId": "e704336260dcb1d775a2ebbad1fd6491",
    "title": "Make overnight oats",
    "status": "completed",
    "isDeleted": "N",
    "isReminderOn": "N",
    "completedTime": 1740606681928,
    "dueTime": 1740606876842,
    "lastModified": 1740606876843,
    "links": (
        "eyJhcHBOYW1lIjoibm90ZSIsImZpbGVJZCI6IkYyMDI1MDIyNjIyMTg0NDQ2Njg2Nno4M2pJ"
        "aGVWN0ZYTCIsImZpbGVQYXRoIjoiL3N0b3JhZ2UvZW11bGF0ZWQvMC9Ob3RlL0hhYml0cy5u"
        "b3RlIiwicGFnZSI6MywicGFnZUlkIjoiUDIwMjUwMjI2MjIyNDM5NDE1Njg2UThtQ0hTYlRL"
        "SURkIn0="
    ),
    "sort": 0,
    "sortCompleted": 2,
    "planerSort": 0,
    "planerSortTime": 1740606876843,
    "sortTime": 1743954561808,
}


async def test_device_task_write_round_trips(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The device's POST /api/file/schedule/task persists and round-trips faithfully.

    Regression: the write route 404'd, so the device could never push planner tasks
    ("private cloud sync failed"). This asserts the captured device payload persists
    with its string id, ungrouped, and rich fields intact, and reads back unchanged
    via task/all.
    """
    resp = await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )
    assert resp.status == 200
    vo = AddScheduleTaskVO.from_dict(await resp.json())
    assert vo.success is True
    # The ack echoes the DEVICE's task id, not a server surrogate.
    assert vo.task_id == "e704336260dcb1d775a2ebbad1fd6491"

    # Read back via the device's task/all.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    assert resp2.status == 200
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert len(all_vo.schedule_task) == 1
    t = all_vo.schedule_task[0]
    assert t.task_id == "e704336260dcb1d775a2ebbad1fd6491"
    assert t.task_list_id is None  # ungrouped
    assert t.title == "Make overnight oats"
    assert t.status == "completed"
    assert t.completed_time == 1740606681928
    assert t.due_time == 1740606876842
    assert t.last_modified == 1740606876843  # device clock, verbatim
    assert t.links == DEVICE_TASK_PUSH["links"]
    assert t.is_deleted == BooleanEnum.NO
    assert t.sort == 0
    assert t.sort_completed == 2
    assert t.planer_sort == 0
    assert t.planer_sort_time == 1740606876843
    assert t.sort_time == 1743954561808


async def test_device_task_write_upserts(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Re-pushing the same task id edits the row instead of duplicating it."""
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )
    edited = {**DEVICE_TASK_PUSH, "title": "Make overnight oats (edited)"}
    await client.post("/api/file/schedule/task", headers=auth_headers, json=edited)

    resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp.json())
    assert len(all_vo.schedule_task) == 1
    assert all_vo.schedule_task[0].title == "Make overnight oats (edited)"


async def test_device_task_delete_tombstones(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A device delete arrives as a POST with isDeleted='Y' and is echoed as a tombstone.

    The device read (task/all) surfaces the tombstone rather than hiding it, so a delete
    reaches every device on the merge instead of resurrecting; the row is retained flagged.
    """
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )
    deleted = {**DEVICE_TASK_PUSH, "isDeleted": "Y"}
    await client.post("/api/file/schedule/task", headers=auth_headers, json=deleted)

    resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp.json())
    assert len(all_vo.schedule_task) == 1
    assert all_vo.schedule_task[0].is_deleted == BooleanEnum.YES


async def test_device_task_list_batch_update(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The device batches edits via PUT /api/file/schedule/task/list.

    Regression (found live in ticket 04): a real device sync pushes edits/completions
    through this batch route, not just the single POST; while unregistered it 404'd, so
    device edits never reached the store. Each item upserts on (user_id, taskId).
    """
    # Seed a task via the single-push route.
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )

    # The device edits it (completes + retitles) via the batch route.
    edited_item = {
        **DEVICE_TASK_PUSH,
        "title": "Make overnight oats (done)",
        "status": "needsAction",
    }
    resp = await client.put(
        "/api/file/schedule/task/list",
        headers=auth_headers,
        json={"updateScheduleTaskList": [edited_item]},
    )
    assert resp.status == 200

    # The edit upserted the existing row (no duplicate) and round-trips.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert len(all_vo.schedule_task) == 1
    t = all_vo.schedule_task[0]
    assert t.task_id == "e704336260dcb1d775a2ebbad1fd6491"
    assert t.title == "Make overnight oats (done)"
    assert t.status == "needsAction"


async def test_device_task_list_batch_delete_tombstones(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A batch item with isDeleted='Y' tombstones; task/all echoes it flagged deleted."""
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )
    deleted_item = {**DEVICE_TASK_PUSH, "isDeleted": "Y"}
    resp = await client.put(
        "/api/file/schedule/task/list",
        headers=auth_headers,
        json={"updateScheduleTaskList": [deleted_item]},
    )
    assert resp.status == 200

    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    # The device read surfaces the tombstone (isDeleted='Y'), not absence.
    assert len(all_vo.schedule_task) == 1
    assert all_vo.schedule_task[0].is_deleted == BooleanEnum.YES


async def test_device_and_cli_tasks_coexist(
    client: TestClient,
    auth_headers: dict[str, str],
    authenticated_client: Client,
) -> None:
    """CLI-created and device-pushed tasks share the store and both appear in task/all."""
    schedule = ScheduleClient(authenticated_client)
    group = await schedule.create_group("Work")
    assert group.task_list_id is not None
    await schedule.create_task(int(group.task_list_id), "CLI task")

    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )

    resp = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp.json())
    assert sorted(t.title for t in all_vo.schedule_task) == [
        "CLI task",
        "Make overnight oats",
    ]


# A second, distinct device task for exercising true multi-item batches.
DEVICE_TASK_PUSH_2 = {
    **DEVICE_TASK_PUSH,
    "taskId": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    "title": "Buy oat milk",
}


async def test_device_task_list_batch_multi_item(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A batch upserts several tasks at once: an edit to an existing row plus a new one.

    The batch route exists to carry *many* tasks in a single sync; every other batch
    test sends a one-element array, so this guards the accumulate/iterate-in-one-
    transaction path against a regression that only shows up with >1 item.
    """
    # Seed one task via the single-push route.
    await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=DEVICE_TASK_PUSH
    )

    # One batch: edit the seeded task AND create a brand-new one.
    edited = {**DEVICE_TASK_PUSH, "title": "Make overnight oats (edited)"}
    resp = await client.put(
        "/api/file/schedule/task/list",
        headers=auth_headers,
        json={"updateScheduleTaskList": [edited, DEVICE_TASK_PUSH_2]},
    )
    assert resp.status == 200

    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    # Exactly two rows: the edited existing one (no duplicate) and the new one.
    by_id = {t.task_id: t for t in all_vo.schedule_task}
    assert len(by_id) == 2
    assert (
        by_id["e704336260dcb1d775a2ebbad1fd6491"].title
        == "Make overnight oats (edited)"
    )
    assert by_id["a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"].title == "Buy oat milk"


async def test_device_task_list_batch_rolls_back_on_invalid_item(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """One invalid item fails the whole batch atomically — no partial writes.

    A valid new task shares the batch with an over-long-title item; the resulting 400
    must leave *neither* persisted, so the device never sees a half-applied batch.
    """
    good = DEVICE_TASK_PUSH_2
    bad = {**DEVICE_TASK_PUSH, "title": "x" * 256}  # exceeds MAX_TITLE_LENGTH

    resp = await client.put(
        "/api/file/schedule/task/list",
        headers=auth_headers,
        # `good` is first, so it flushes before `bad` fails — proving the rollback
        # unwinds an already-applied item, not just the failing one.
        json={"updateScheduleTaskList": [good, bad]},
    )
    assert resp.status == 400

    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert all_vo.schedule_task == []


async def test_device_task_list_batch_skips_malformed_item(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """An item with a blank taskId is skipped; well-formed items in the batch still land.

    (A *missing* taskId is rejected at DTO parse time, since the batch item type requires
    it; a present-but-empty id is the case the route's skip guard actually handles.)
    """
    malformed = {**DEVICE_TASK_PUSH, "taskId": ""}

    resp = await client.put(
        "/api/file/schedule/task/list",
        headers=auth_headers,
        json={"updateScheduleTaskList": [DEVICE_TASK_PUSH_2, malformed]},
    )
    assert resp.status == 200

    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    # Only the well-formed item was stored; the blank-id item was skipped.
    assert [t.task_id for t in all_vo.schedule_task] == [
        "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    ]


async def test_device_task_write_missing_task_id_returns_400(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A single device push with no taskId is rejected — the upsert has no key to bind to."""
    no_id = {k: v for k, v in DEVICE_TASK_PUSH.items() if k != "taskId"}

    resp = await client.post(
        "/api/file/schedule/task", headers=auth_headers, json=no_id
    )
    assert resp.status == 400

    # Nothing was stored.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert all_vo.schedule_task == []


async def test_device_task_write_title_too_long_returns_400(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A single device push whose title exceeds the limit is rejected with 400."""
    bad = {**DEVICE_TASK_PUSH, "title": "x" * 256}

    resp = await client.post("/api/file/schedule/task", headers=auth_headers, json=bad)
    assert resp.status == 400

    # The rejected push left no row behind.
    resp2 = await client.post(
        "/api/file/schedule/task/all", headers=auth_headers, json={}
    )
    all_vo = ScheduleTaskAllVO.from_dict(await resp2.json())
    assert all_vo.schedule_task == []
