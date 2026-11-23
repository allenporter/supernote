"""HTTP iCalendar export tests for `GET /api/schedule/feed.ics`."""

from __future__ import annotations

import base64
import json

from ical.calendar_stream import IcsCalendarStream

from supernote.client.schedule import ScheduleClient
from supernote.models.schedule import ScheduleTaskLinkDTO


async def test_export_empty_calendar(schedule_client: ScheduleClient) -> None:
    """Verify exporting a calendar when the user has no schedule tasks."""
    ics_text = await schedule_client.get_ical_feed()

    assert "BEGIN:VCALENDAR" in ics_text
    assert "END:VCALENDAR" in ics_text

    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert calendar is not None
    assert len(calendar.todos) == 0


async def test_export_ungrouped_inbox_task(schedule_client: ScheduleClient) -> None:
    """Verify exporting an ungrouped Inbox task produces no categories."""
    await schedule_client.create_task(None, "Inbox Task")

    ics_text = await schedule_client.get_ical_feed()
    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert len(calendar.todos) == 1
    assert calendar.todos[0].categories == []


async def test_export_calendar_tasks_roundtrip(schedule_client: ScheduleClient) -> None:
    """Verify creating tasks via HTTP and round-trip parsing the `.ics` feed."""
    group = await schedule_client.create_group("Project Alpha")
    assert group.task_list_id is not None
    group_id = group.task_list_id

    task1 = await schedule_client.create_task(
        group_id=group_id,
        title="Review PR #42",
        detail="Check iCal export implementation",
        status="needsAction",
        importance="high",
        due_time=1722643200000,
    )
    assert task1.task_id is not None

    task2 = await schedule_client.create_task(
        group_id=group_id,
        title="Deploy to Staging",
        detail="Run schema migrations first",
        status="completed",
        completed_time_ms=1722646800000,
    )
    assert task2.task_id is not None

    ics_text = await schedule_client.get_ical_feed()
    assert "BEGIN:VCALENDAR" in ics_text
    assert "BEGIN:VTODO" in ics_text

    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert calendar is not None
    assert len(calendar.todos) == 2

    summaries = {todo.summary for todo in calendar.todos}
    assert summaries == {"Review PR #42", "Deploy to Staging"}

    todo1 = next(t for t in calendar.todos if t.summary == "Review PR #42")
    assert todo1.description == "Check iCal export implementation"
    assert todo1.categories == ["Project Alpha"]
    assert todo1.priority == 1
    assert todo1.uid == f"supernote-task-{task1.task_id}@supernote"


async def test_export_calendar_task_list_filtering(
    schedule_client: ScheduleClient,
) -> None:
    """Verify filtering `.ics` feed by a specific taskListId excludes other groups."""
    group_a = await schedule_client.create_group("Work")
    group_b = await schedule_client.create_group("Personal")
    assert group_a.task_list_id is not None
    assert group_b.task_list_id is not None

    await schedule_client.create_task(group_a.task_list_id, "Work Task")
    await schedule_client.create_task(group_b.task_list_id, "Personal Task")

    ics_text_a = await schedule_client.get_ical_feed(group_id=group_a.task_list_id)
    calendar_a = IcsCalendarStream.calendar_from_ics(ics_text_a)
    assert len(calendar_a.todos) == 1
    assert calendar_a.todos[0].summary == "Work Task"


async def test_export_task_with_file_path_link(
    schedule_client: ScheduleClient,
) -> None:
    """Verify decoding and exporting a task link encoded with `filePath` and `taskTitle`."""
    group = await schedule_client.create_group("Daily Notes")
    assert group.task_list_id is not None
    raw_link = {
        "appName": "Note",
        "filePath": "Note/2026_Daily.note",
        "fileId": "99887766",
        "page": 3,
        "pageId": "P20260101",
        "taskTitle": "Follow up on design",
    }
    links_b64 = base64.b64encode(json.dumps(raw_link).encode("utf-8")).decode("utf-8")

    decoded = ScheduleTaskLinkDTO.from_b64(links_b64)
    assert decoded.path == "Note/2026_Daily.note"
    assert decoded.task_title == "Follow up on design"

    await schedule_client.create_task(
        group.task_list_id,
        "Follow up on design",
        links=links_b64,
    )

    ics_text = await schedule_client.get_ical_feed()
    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert len(calendar.todos) == 1
    todo = calendar.todos[0]
    assert todo.summary == "Follow up on design"
    assert todo.description is not None
    assert "Note/2026_Daily.note" in todo.description
