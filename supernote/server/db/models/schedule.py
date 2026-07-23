import time
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Index, String, false
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
    """Individual Tasks.

    Shared by the CLI (insert-only, server-generated int ``task_id``) and the device
    planner sync (upsert keyed on ``device_task_id``). See the store-design ADR
    ``.scratch/zero-banner-sync/assets/02-planner-store-design.md`` for the rationale.
    """

    __tablename__ = "t_schedule_task"

    __table_args__ = (
        # Device tasks upsert on (user_id, device_task_id). NULL device_task_id (all
        # CLI rows) are distinct under a UNIQUE index, so this binds device rows only.
        Index(
            "uq_schedule_task_device_id",
            "user_id",
            "device_task_id",
            unique=True,
        ),
    )

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Server surrogate ID (never exposed to the device)."""

    device_task_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """The device's own opaque string task id; NULL for CLI-created tasks."""

    task_list_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, index=True, nullable=True
    )
    """Link back to task list; NULL for ungrouped (device) tasks."""

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
    """Server update time in epoch milliseconds (bookkeeping, server clock)."""

    # --- Device planner fields (all faithful to the device's push shape) ---

    links: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Opaque base64 JSON blob linking a task to a note page; stored verbatim."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    """Soft-delete tombstone; the device deletes by re-pushing with isDeleted='Y'."""

    last_modified: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """The device's own lastModified (device clock); distinct from update_time."""

    # Sort family. Nullable so "device omitted" (NULL) is distinct from "sent 0".
    sort: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sort_completed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    planer_sort: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    planer_sort_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sort_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Not seen in captured device traffic; carried for DTO/VO parity.
    all_sort: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    all_sort_completed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    all_sort_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
