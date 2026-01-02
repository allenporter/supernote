import logging
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
            return bool(result.rowcount > 0)  # type: ignore[attr-defined]

    # Task Operations

    async def create_task(
        self,
        user_id: int,
        group_id: int,
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

    async def list_tasks(
        self,
        user_id: int,
        group_id: int | None = None,
    ) -> list[ScheduleTaskDO]:
        """List tasks for a user, optionally filtered by group."""
        async with self.session_manager.session() as session:
            query = select(ScheduleTaskDO).where(ScheduleTaskDO.user_id == user_id)
            if group_id is not None:
                query = query.where(ScheduleTaskDO.task_list_id == group_id)

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
            return bool(result.rowcount > 0)  # type: ignore[attr-defined]
