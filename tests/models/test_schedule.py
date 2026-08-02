"""Tests for Schedule data models."""

from supernote.models.schedule import (
    AddScheduleTaskDTO,
    AddScheduleTaskGroupDTO,
    ScheduleRecurTaskItem,
    ScheduleTaskAllVO,
    ScheduleTaskGroupItem,
    ScheduleTaskGroupVO,
    ScheduleTaskInfo,
    UpdateScheduleTaskDTO,
)


def test_schedule_task_group_item() -> None:
    item = ScheduleTaskGroupItem(
        task_list_id="group1", user_id=12345, title="My Group", create_time=1600000000
    )
    assert item.to_dict()["taskListId"] == "group1"
    assert item.to_dict()["userId"] == 12345


def test_schedule_recur_task_item() -> None:
    item = ScheduleRecurTaskItem(
        task_id="task1", recurrence_id="rec1", due_time=1600000000
    )
    assert item.to_dict()["taskId"] == "task1"
    assert item.to_dict()["dueTime"] == 1600000000


def test_schedule_task_info() -> None:
    recur_item = ScheduleRecurTaskItem(task_id="subtask1")
    info = ScheduleTaskInfo(task_id="main_task", schedule_recur_task=[recur_item])
    assert info.task_id == "main_task"
    assert len(info.schedule_recur_task) == 1

    data = info.to_dict()
    assert data["taskId"] == "main_task"
    assert data["scheduleRecurTask"][0]["taskId"] == "subtask1"

    info2 = ScheduleTaskInfo.from_dict(data)
    assert info2.schedule_recur_task[0].task_id == "subtask1"


def test_add_schedule_task_group_dto() -> None:
    dto = AddScheduleTaskGroupDTO(title="New Group")
    assert dto.to_dict()["title"] == "New Group"


def test_add_schedule_task_dto() -> None:
    dto = AddScheduleTaskDTO(title="New Task", task_list_id="group1")
    assert dto.to_dict()["title"] == "New Task"
    assert dto.to_dict()["taskListId"] == "group1"


def test_update_schedule_task_dto() -> None:
    dto = UpdateScheduleTaskDTO(
        task_id="task1", title="Updated Task", last_modified=1600000001
    )
    assert dto.to_dict()["taskId"] == "task1"
    assert dto.to_dict()["lastModified"] == 1600000001


def test_schedule_task_group_vo() -> None:
    item = ScheduleTaskGroupItem(task_list_id="g1")
    vo = ScheduleTaskGroupVO(schedule_task_group=[item], page_token="next_page")
    assert vo.to_dict()["pageToken"] == "next_page"
    assert vo.to_dict()["scheduleTaskGroup"][0]["taskListId"] == "g1"


def test_schedule_task_all_vo() -> None:
    task = ScheduleTaskInfo(task_id="t1")
    vo = ScheduleTaskAllVO(schedule_task=[task], next_sync_token=999)
    assert vo.to_dict()["nextSyncToken"] == 999
    assert vo.to_dict()["scheduleTask"][0]["taskId"] == "t1"
