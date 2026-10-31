"""ORM models (`ScheduleTaskGroupDO` and `ScheduleTaskDO`) for tasks and task lists.

Persists user task lists (`t_schedule_task_group`) and individual schedule tasks
(`t_schedule_task`) including status, importance, due/completed timestamps, RFC 5545
recurrence rules, base64-encoded `.note` page links, and sort indexes. Managed by
`supernote.server.services.schedule.ScheduleService` and exported by
`supernote.server.services.ical_export.ICalExportService`. See `supernote.guides.schedule_api`.
"""

import time

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class ScheduleTaskGroupDO(Base):
    """Groups of tasks (e.g., 'Inbox', 'Work', 'Personal')."""

    __tablename__ = "t_schedule_task_group"

    task_list_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(next_id())
    )
    """Unique task group ID."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """User ID."""

    title: Mapped[str] = mapped_column(String, nullable=False)
    """Title."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation time in epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Update time in epoch milliseconds."""


class ScheduleTaskDO(Base):
    """Individual Tasks."""

    __tablename__ = "t_schedule_task"

    task_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(next_id())
    )
    """Unique task ID."""

    task_list_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    """Link back to task list."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """User ID."""

    title: Mapped[str] = mapped_column(String, nullable=False)
    """A summary of the task."""

    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    """The task description."""

    # Status: 'completed', 'needsAction', etc.
    status: Mapped[str] = mapped_column(String, default="needsAction")
    """The status of the task."""

    importance: Mapped[str | None] = mapped_column(String, nullable=True)
    """The importance of the task."""

    due_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Due time in epoch milliseconds."""

    completed_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Completed time in epoch milliseconds."""

    # RRule string
    recurrence: Mapped[str | None] = mapped_column(String, nullable=True)
    """The recurrence rule for the task."""

    is_reminder_on: Mapped[bool] = mapped_column(default=False)
    """Whether the task has a reminder."""

    links: Mapped[str | None] = mapped_column(String, nullable=True)
    """Base64 encoded JSON description of document link."""

    sort: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_completed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    planer_sort: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    all_sort: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    all_sort_completed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    sort_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    planer_sort_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    all_sort_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation time in epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Update time in epoch milliseconds."""
