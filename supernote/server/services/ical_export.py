"""iCalendar export service for converting tasks into RFC 5545 VTODO feeds."""

import binascii
import logging
from datetime import datetime, timezone

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.exceptions import CalendarParseError
from ical.todo import Todo, TodoStatus
from ical.types import Recur

from supernote.models.schedule import ScheduleTaskInfo, ScheduleTaskLinkDTO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.schedule import ScheduleService

logger = logging.getLogger(__name__)


def ms_to_datetime(ms: int | None) -> datetime | None:
    """Convert epoch milliseconds timestamp to a UTC aware datetime object."""
    if not ms or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def map_importance_to_priority(importance: str | None) -> int | None:
    """Map Supernote task importance to RFC 5545 priority (1-9)."""
    if not importance:
        return None
    imp_lower = str(importance).lower()
    if imp_lower in ("high", "1"):
        return 1
    if imp_lower in ("normal", "medium", "5"):
        return 5
    if imp_lower in ("low", "9"):
        return 9
    return None


def format_task_description(detail: str | None, links_b64: str | None) -> str | None:
    """Combine task detail text with formatted document deep link info."""
    parts: list[str] = []
    if detail:
        parts.append(detail)

    if links_b64:
        try:
            link = ScheduleTaskLinkDTO.from_b64(links_b64)
            link_info = (
                f"\n--- Supernote Document Link ---\n"
                f"App: {link.app_name}\n"
                f"Path: {link.path}\n"
                f"Page: {link.page}"
            )
            parts.append(link_info)
        except (ValueError, TypeError, binascii.Error) as err:
            logger.warning("Failed to decode task link base64: %s", err)

    return "\n".join(parts) if parts else None


def task_to_vtodo(
    task: ScheduleTaskDO | ScheduleTaskInfo,
    group_title: str | None = None,
) -> Todo:
    """Convert a Supernote schedule task object to an ical.todo.Todo object."""
    task_id = str(task.task_id) if task.task_id is not None else "unknown"
    uid = f"supernote-task-{task_id}@supernote"

    # Status mapping
    status_str = task.status or "needsAction"
    completed_dt = ms_to_datetime(task.completed_time)

    if status_str == "completed" or completed_dt is not None:
        todo_status = TodoStatus.COMPLETED
    else:
        todo_status = TodoStatus.NEEDS_ACTION

    due_dt = ms_to_datetime(task.due_time)
    created_dt = ms_to_datetime(getattr(task, "create_time", None))

    last_mod_ms = getattr(task, "last_modified", None) or getattr(
        task, "update_time", None
    )
    last_mod_dt = ms_to_datetime(last_mod_ms)

    description = format_task_description(
        task.detail,
        getattr(task, "links", None),
    )

    # Recurrence rule
    recurrence_str = task.recurrence
    rrule_obj = None
    if recurrence_str:
        try:
            rrule_obj = Recur.from_rrule(recurrence_str)
        except (ValueError, TypeError, AttributeError, CalendarParseError) as err:
            logger.warning(
                "Failed to parse recurrence rule '%s': %s", recurrence_str, err
            )

    # Categories (Task Group Title)
    categories = [group_title] if group_title else None

    return Todo(
        uid=uid,
        summary=task.title or "",
        description=description,
        status=todo_status,
        due=due_dt,
        completed=completed_dt if todo_status == TodoStatus.COMPLETED else None,
        created=created_dt,
        last_modified=last_mod_dt,
        categories=categories,
        rrule=rrule_obj,
        priority=map_importance_to_priority(task.importance),
    )


class ICalExportService:
    """Service for exporting Supernote tasks to RFC 5545 iCalendar feeds."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        schedule_service: ScheduleService,
    ):
        """Initialize the iCal export service."""
        self.session_manager = session_manager
        self.schedule_service = schedule_service

    async def export_calendar(
        self,
        user_id: int,
        task_list_id: str | None = None,
    ) -> str:
        """Export user tasks to an RFC 5545 compliant iCalendar (.ics) string."""
        # 1. Fetch group titles map
        groups = await self.schedule_service.list_groups(user_id)
        groups_map = {g.task_list_id: g.title for g in groups}

        # 2. Fetch tasks for user
        tasks = await self.schedule_service.list_tasks(user_id, group_id=task_list_id)

        # 3. Build iCalendar object
        calendar = Calendar()
        for task in tasks:
            group_title = (
                groups_map.get(task.task_list_id) if task.task_list_id else None
            )
            todo = task_to_vtodo(task, group_title=group_title)
            calendar.todos.append(todo)

        # 4. Serialize to iCalendar stream
        return IcsCalendarStream.calendar_to_ics(calendar)
