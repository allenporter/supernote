import logging
import time
from typing import Any, Optional

from sqlalchemy import delete, select, update

from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO
from supernote.server.db.session import DatabaseSessionManager

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 255
MAX_DETAIL_LENGTH = 1 * 1024 * 1024  # 1MB


class ScheduleService:
    """Schedule service."""

    def __init__(self, session_manager: DatabaseSessionManager):
        """Initialize the schedule service."""
        self.session_manager = session_manager

    # Task Group Operations

    async def create_group(self, user_id: int, title: str) -> ScheduleTaskGroupDO:
        """Create a new task group."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        async with self.session_manager.session() as session:
            group = ScheduleTaskGroupDO(user_id=user_id, title=title)
            session.add(group)
            # Flush to generate ID
            await session.flush()
            # Commit to persist
            await session.commit()
            # Refresh to get defaults if any
            await session.refresh(group)
            return group

    async def list_groups(self, user_id: int) -> list[ScheduleTaskGroupDO]:
        """List all task groups for a user."""
        async with self.session_manager.session() as session:
            stmt = (
                select(ScheduleTaskGroupDO)
                .where(ScheduleTaskGroupDO.user_id == user_id)
                .order_by(ScheduleTaskGroupDO.create_time.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_group(self, user_id: int, group_id: int) -> bool:
        """Delete a task group. Returns True if found and deleted."""
        # TODO: Handle cascade delete of tasks?
        # For now, simplistic delete.
        async with self.session_manager.session() as session:
            stmt = delete(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == group_id,
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    # Task Operations

    async def create_task(
        self,
        user_id: int,
        group_id: int | None,
        title: str,
        detail: str = "",
        status: str = "needsAction",
        importance: str | None = None,
        due_time: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool = False,
    ) -> ScheduleTaskDO:
        """Create a new task."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        if len(detail) > MAX_DETAIL_LENGTH:
            raise ValueError("Detail is too long")
        async with self.session_manager.session() as session:
            task = ScheduleTaskDO(
                user_id=user_id,
                task_list_id=group_id,
                title=title,
                detail=detail,
                status=status,
                importance=importance,
                due_time=due_time,
                recurrence=recurrence,
                is_reminder_on=is_reminder_on,
            )
            session.add(task)
            await session.flush()
            await session.commit()
            await session.refresh(task)
            return task

    async def upsert_task(
        self,
        user_id: int,
        *,
        device_task_id: str,
        title: str,
        task_list_id: int | None = None,
        detail: str | None = None,
        status: str = "needsAction",
        importance: str | None = None,
        due_time: int | None = None,
        completed_time: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool = False,
        links: str | None = None,
        is_deleted: bool = False,
        last_modified: int | None = None,
        sort: int | None = None,
        sort_completed: int | None = None,
        planer_sort: int | None = None,
        planer_sort_time: int | None = None,
        sort_time: int | None = None,
        all_sort: int | None = None,
        all_sort_completed: int | None = None,
        all_sort_time: int | None = None,
    ) -> ScheduleTaskDO:
        """Upsert a device-authored task, keyed on ``(user_id, device_task_id)``.

        This is the device planner's write seam: unlike the CLI's insert-only
        :meth:`create_task`, re-pushing the same ``device_task_id`` updates the
        existing row (edit/complete/delete all arrive this way). A delete is a push
        with ``is_deleted=True`` which tombstones the row rather than removing it. The
        server surrogate ``task_id`` is generated once and never exposed to the device.
        """
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        if detail is not None and len(detail) > MAX_DETAIL_LENGTH:
            raise ValueError("Detail is too long")

        # Fields that come from the device push; task_id/user_id/device_task_id are the
        # stable identity and are not part of the mutable set.
        fields = {
            "task_list_id": task_list_id,
            "title": title,
            "detail": detail,
            "status": status,
            "importance": importance,
            "due_time": due_time,
            "completed_time": completed_time,
            "recurrence": recurrence,
            "is_reminder_on": is_reminder_on,
            "links": links,
            "is_deleted": is_deleted,
            "last_modified": last_modified,
            "sort": sort,
            "sort_completed": sort_completed,
            "planer_sort": planer_sort,
            "planer_sort_time": planer_sort_time,
            "sort_time": sort_time,
            "all_sort": all_sort,
            "all_sort_completed": all_sort_completed,
            "all_sort_time": all_sort_time,
            "update_time": int(time.time() * 1000),
        }

        async with self.session_manager.session() as session:
            stmt = select(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.device_task_id == device_task_id,
            )
            task = (await session.execute(stmt)).scalar_one_or_none()

            if task is None:
                task = ScheduleTaskDO(
                    user_id=user_id, device_task_id=device_task_id, **fields
                )
                session.add(task)
            else:
                for key, value in fields.items():
                    setattr(task, key, value)

            await session.flush()
            await session.commit()
            await session.refresh(task)
            return task

    async def list_tasks(
        self,
        user_id: int,
        group_id: int | None = None,
        include_deleted: bool = False,
    ) -> list[ScheduleTaskDO]:
        """List tasks for a user, optionally filtered by group.

        Soft-deleted (tombstoned) device tasks are hidden unless ``include_deleted`` is
        set, so a device delete reflects as the task's absence on the next sync.
        """
        async with self.session_manager.session() as session:
            query = select(ScheduleTaskDO).where(ScheduleTaskDO.user_id == user_id)
            if group_id is not None:
                query = query.where(ScheduleTaskDO.task_list_id == group_id)
            if not include_deleted:
                query = query.where(ScheduleTaskDO.is_deleted.is_(False))

            query = query.order_by(ScheduleTaskDO.create_time.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_task(
        self, user_id: int, task_id: int, **kwargs: Any
    ) -> Optional[ScheduleTaskDO]:
        """Update a task."""
        # Clean kwargs to only allow update of specific fields?
        # For simplicity, we assume caller passes valid fields that match DO columns.
        allowed_fields = {
            "title",
            "detail",
            "status",
            "importance",
            "due_time",
            "completed_time",
            "recurrence",
            "is_reminder_on",
            "task_list_id",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        async with self.session_manager.session() as session:
            stmt = (
                update(ScheduleTaskDO)
                .where(
                    ScheduleTaskDO.user_id == user_id, ScheduleTaskDO.task_id == task_id
                )
                .values(**updates)
                .execution_options(synchronize_session="fetch")
            )
            await session.execute(stmt)
            await session.commit()

            # Retrieve updated
            stmt_get = select(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id, ScheduleTaskDO.task_id == task_id
            )
            result = await session.execute(stmt_get)
            return result.scalar_one_or_none()

    async def delete_task(self, user_id: int, task_id: int) -> bool:
        """Delete a task."""
        async with self.session_manager.session() as session:
            stmt = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id, ScheduleTaskDO.task_id == task_id
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
