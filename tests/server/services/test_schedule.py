import pytest

from supernote.models.schedule import (
    AddScheduleTaskDTO,
    ScheduleTaskInfo,
    UpdateScheduleTaskDTO,
)
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.schedule import (
    DEVICE_TASK_PASSTHROUGH_FIELDS,
    ScheduleService,
)


def test_passthrough_fields_agree_across_dto_do_vo() -> None:
    """The verbatim passthrough couples names across the DTO, the DO, and the VO.

    Nothing coerces these fields on the way through — the write path reads them off
    the DTO by name, stores them on the row by name, and the read path emits them on
    the VO by name (see ``DEVICE_TASK_PASSTHROUGH_FIELDS``). If any name drifts out of
    one of the three shapes the coupling breaks at runtime (an ``AttributeError`` on
    read, or a silently dropped column), so pin the agreement here instead.
    """
    do_columns = set(ScheduleTaskDO.__mapper__.columns.keys())
    vo_fields = set(ScheduleTaskInfo.__dataclass_fields__.keys())
    add_dto_fields = set(AddScheduleTaskDTO.__dataclass_fields__.keys())
    update_dto_fields = set(UpdateScheduleTaskDTO.__dataclass_fields__.keys())
    for name in DEVICE_TASK_PASSTHROUGH_FIELDS:
        assert name in do_columns, f"{name!r} missing from ScheduleTaskDO"
        assert name in vo_fields, f"{name!r} missing from ScheduleTaskInfo"
        assert name in add_dto_fields, f"{name!r} missing from AddScheduleTaskDTO"
        assert name in update_dto_fields, f"{name!r} missing from UpdateScheduleTaskDTO"
    # last_modified is deliberately NOT verbatim (device-clock-else-server-clock
    # fallback on read), so it must stay out of the passthrough tuple.
    assert "last_modified" not in DEVICE_TASK_PASSTHROUGH_FIELDS


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


async def test_delete_task_soft_deletes_with_stamp(
    schedule_service: ScheduleService,
) -> None:
    """CLI delete_task tombstones (not hard-deletes) and stamps last_modified.

    A hard delete would drop the row, so the device's differential sync never learns of
    the deletion and resurrects the task. Instead the row survives as an isDeleted='Y'
    tombstone with a fresh last_modified, so the device merge removes its local copy.
    """
    user_id = 909
    task = await schedule_service.create_task(user_id, None, "Delete me")
    assert task.last_modified is None

    deleted = await schedule_service.delete_task(user_id, task.task_id)
    assert deleted is True

    # CLI/default read hides the tombstone — the task still "disappears" for the CLI.
    assert await schedule_service.list_tasks(user_id) == []

    # ...but the tombstone is retained and carries a fresh last_modified so it out-versions
    # whatever copy the device holds (the device read passes include_deleted=True).
    tombstoned = await schedule_service.list_tasks(user_id, include_deleted=True)
    assert len(tombstoned) == 1
    assert tombstoned[0].is_deleted is True
    assert tombstoned[0].last_modified is not None
    assert tombstoned[0].last_modified == tombstoned[0].update_time

    # Re-deleting an already-tombstoned task matches no live row.
    assert await schedule_service.delete_task(user_id, task.task_id) is False


async def test_purge_acked_task_resolves_both_id_shapes(
    schedule_service: ScheduleService,
) -> None:
    """The delete-ack purges by whichever id task/all emitted: device id or surrogate id.

    task/all echoes a device row under its device_task_id but a CLI row under its surrogate
    task_id (it has no device id). The device acks with that id, so the purge must resolve
    both — otherwise the CLI tombstone is never purged and task/all re-serves it forever,
    and the device re-acks it every sync (the bug this replaces).
    """
    user_id = 911

    # Device row: acked by its device_task_id.
    device_id = "aaaa1111bbbb2222cccc3333dddd4444"
    await schedule_service.upsert_task(
        user_id, device_task_id=device_id, title="Device tombstone", is_deleted=True
    )
    assert await schedule_service.purge_acked_task(user_id, device_id) is True
    # Idempotent: a re-issued ack for the now-gone row is a no-op.
    assert await schedule_service.purge_acked_task(user_id, device_id) is False

    # CLI row: no device_task_id, so task/all emits str(task_id); the ack arrives as that.
    cli_task = await schedule_service.create_task(user_id, None, "CLI tombstone")
    await schedule_service.delete_task(user_id, cli_task.task_id)
    assert len(await schedule_service.list_tasks(user_id, include_deleted=True)) == 1

    surrogate_id = str(cli_task.task_id)
    assert await schedule_service.purge_acked_task(user_id, surrogate_id) is True
    assert await schedule_service.list_tasks(user_id, include_deleted=True) == []
    assert await schedule_service.purge_acked_task(user_id, surrogate_id) is False


async def test_upsert_task_isolation(schedule_service: ScheduleService) -> None:
    """The same device task id under two users are distinct rows (unique per user)."""
    device_id = "0000000000000000000000000000ffff"
    await schedule_service.upsert_task(201, device_task_id=device_id, title="U1")
    await schedule_service.upsert_task(202, device_task_id=device_id, title="U2")

    u1 = await schedule_service.list_tasks(201)
    u2 = await schedule_service.list_tasks(202)
    assert [t.title for t in u1] == ["U1"]
    assert [t.title for t in u2] == ["U2"]


async def test_upsert_tasks_batch_applies_all(
    schedule_service: ScheduleService,
) -> None:
    """A batch upserts every item in one transaction (insert new + edit existing)."""
    user_id = 888
    existing = "1111111111111111111111111111aaaa"
    await schedule_service.upsert_task(user_id, device_task_id=existing, title="First")

    await schedule_service.upsert_tasks(
        user_id,
        [
            {"device_task_id": existing, "title": "First (edited)"},
            {"device_task_id": "2222222222222222222222222222bbbb", "title": "Second"},
        ],
    )

    tasks = await schedule_service.list_tasks(user_id)
    # The existing row was updated in place (no duplicate); the new row was inserted.
    assert sorted(t.title for t in tasks) == ["First (edited)", "Second"]


async def test_upsert_tasks_batch_is_atomic(
    schedule_service: ScheduleService,
) -> None:
    """A validation error on any item rolls the whole batch back — no partial writes."""
    user_id = 889
    with pytest.raises(ValueError):
        await schedule_service.upsert_tasks(
            user_id,
            [
                {"device_task_id": "3333333333333333333333333333cccc", "title": "Good"},
                # Over-long title fails validation *after* the good item has flushed.
                {
                    "device_task_id": "4444444444444444444444444444dddd",
                    "title": "x" * 256,
                },
            ],
        )

    # The good item, flushed before the failure, was rolled back with the bad one.
    assert await schedule_service.list_tasks(user_id) == []


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
