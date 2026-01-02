import time
from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class ScheduleTaskGroupDO(Base):
    """Groups of tasks (e.g., 'Inbox', 'Work', 'Personal')."""

    __tablename__ = "t_schedule_task_group"

    # In legacy/docs, task_list_id might be a string (UUID) or Int.
    # Using unique_id Int for consistency, but mapping to String if API requires it.
    task_list_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_id
    )
    """Unique ID."""

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

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Unique ID."""

    task_list_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """Link back to task list."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """User ID."""

    title: Mapped[str] = mapped_column(String, nullable=False)
    """A summary of the task."""

    detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """The task description."""

    # Status: 'completed', 'needsAction', etc.
    status: Mapped[str] = mapped_column(String, default="needsAction")
    """The status of the task."""

    importance: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """The importance of the task."""

    due_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """Due time in epoch milliseconds."""

    completed_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """Completed time in epoch milliseconds."""

    # RRule string
    recurrence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """The recurrence rule for the task."""

    is_reminder_on: Mapped[bool] = mapped_column(default=False)
    """Whether the task has a reminder."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation time in epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Update time in epoch milliseconds."""
