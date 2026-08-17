import time

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


def generate_id_string() -> str:
    """Generate default unique ID as string."""
    return str(next_id())


class ScheduleTaskGroupDO(Base):
    """Groups of tasks (e.g., 'Inbox', 'Work', 'Personal')."""

    __tablename__ = "t_schedule_task_group"

    task_list_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=generate_id_string
    )
    """Unique ID string."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """User ID."""

    title: Mapped[str] = mapped_column(String, nullable=False)
    """Title."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation time in epoch milliseconds."""


class ScheduleTaskDO(Base):
    """Individual Tasks."""

    __tablename__ = "t_schedule_task"

    task_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=generate_id_string
    )
    """Unique ID string."""

    task_list_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    """Link back to task list."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
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
