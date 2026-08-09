"""Unit tests for ICalExportService task conversion and iCalendar stream export."""

import pytest
from ical.calendar_stream import IcsCalendarStream

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.ical_export import ICalExportService
from supernote.server.services.schedule import ScheduleService


@pytest.fixture
async def schedule_service(session_manager: DatabaseSessionManager) -> ScheduleService:
    """Fixture for ScheduleService."""
    return ScheduleService(session_manager)


@pytest.fixture
async def ical_export_service(
    session_manager: DatabaseSessionManager,
    schedule_service: ScheduleService,
) -> ICalExportService:
    """Fixture for ICalExportService."""
    return ICalExportService(session_manager, schedule_service)


async def test_export_empty_calendar(
    ical_export_service: ICalExportService,
) -> None:
    """Test exporting a calendar when the user has no schedule tasks."""
    user_id = 999
    ics_text = await ical_export_service.export_calendar(user_id)

    assert "BEGIN:VCALENDAR" in ics_text
    assert "END:VCALENDAR" in ics_text

    # Round-trip parsing with ical library
    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert calendar is not None
    assert len(calendar.todos) == 0


async def test_export_calendar_tasks_roundtrip(
    schedule_service: ScheduleService,
    ical_export_service: ICalExportService,
) -> None:
    """Test creating tasks and verifying iCal export round-trip parsing."""
    user_id = 888
    group = await schedule_service.create_group(user_id, "Project Alpha")
    group_id = group.task_list_id

    # Create test tasks
    task1 = await schedule_service.create_task(
        user_id=user_id,
        group_id=group_id,
        title="Review PR #42",
        detail="Check iCal export implementation",
        status="needsAction",
        importance="high",
        due_time=1722643200000,
    )
    task2 = await schedule_service.create_task(
        user_id=user_id,
        group_id=group_id,
        title="Deploy to Staging",
        detail="Run schema migrations first",
        status="completed",
    )
    await schedule_service.update_task(
        user_id, task2.task_id, completed_time=1722646800000
    )

    # Export calendar for user
    ics_text = await ical_export_service.export_calendar(user_id)
    assert isinstance(ics_text, str)
    assert "BEGIN:VCALENDAR" in ics_text
    assert "BEGIN:VTODO" in ics_text

    # Parse exported iCal stream back into Calendar object
    calendar = IcsCalendarStream.calendar_from_ics(ics_text)
    assert calendar is not None
    assert len(calendar.todos) == 2

    # Verify task properties match created tasks
    summaries = {todo.summary for todo in calendar.todos}
    assert "Review PR #42" in summaries
    assert "Deploy to Staging" in summaries

    todo1 = next(t for t in calendar.todos if t.summary == "Review PR #42")
    assert todo1.description == "Check iCal export implementation"
    assert todo1.categories == ["Project Alpha"]
    assert todo1.priority == 1
    assert todo1.uid == f"supernote-task-{task1.task_id}@supernote"


async def test_export_calendar_task_list_filtering(
    schedule_service: ScheduleService,
    ical_export_service: ICalExportService,
) -> None:
    """Test exporting calendar filtered by a specific task list/group."""
    user_id = 777
    group_a = await schedule_service.create_group(user_id, "Work")
    group_b = await schedule_service.create_group(user_id, "Personal")

    await schedule_service.create_task(user_id, group_a.task_list_id, "Work Task")
    await schedule_service.create_task(user_id, group_b.task_list_id, "Personal Task")

    # Export only Group A
    ics_text_a = await ical_export_service.export_calendar(
        user_id, task_list_id=group_a.task_list_id
    )
    calendar_a = IcsCalendarStream.calendar_from_ics(ics_text_a)
    assert len(calendar_a.todos) == 1
    assert calendar_a.todos[0].summary == "Work Task"
