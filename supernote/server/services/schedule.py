import logging
import time
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult

from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO
from supernote.server.db.session import DatabaseSessionManager

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 255
MAX_DETAIL_LENGTH = 1 * 1024 * 1024  # 1MB

# Task field sets for service operations and updates
TASK_BASE_FIELDS: set[str] = {
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

TASK_SORT_FIELDS: set[str] = {
    "sort",
    "sort_completed",
    "planer_sort",
    "all_sort",
    "all_sort_completed",
    "sort_time",
    "planer_sort_time",
    "all_sort_time",
}

TASK_ALLOWED_UPDATE_FIELDS: set[str] = TASK_BASE_FIELDS | TASK_SORT_FIELDS | {"links"}


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
            query = (
                select(ScheduleTaskGroupDO)
                .where(ScheduleTaskGroupDO.user_id == user_id)
                .order_by(ScheduleTaskGroupDO.create_time.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_group(
        self, user_id: int, group_id: str
    ) -> ScheduleTaskGroupDO | None:
        """Get a task group by ID."""
        async with self.session_manager.session() as session:
            stmt = select(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == group_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_group(
        self, user_id: int, group_id: str, title: str
    ) -> ScheduleTaskGroupDO | None:
        """Update a task group title."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        async with self.session_manager.session() as session:
            stmt = (
                update(ScheduleTaskGroupDO)
                .where(
                    ScheduleTaskGroupDO.user_id == user_id,
                    ScheduleTaskGroupDO.task_list_id == group_id,
                )
                .values(title=title)
                .execution_options(synchronize_session="fetch")
            )
            await session.execute(stmt)
            await session.commit()

            # Retrieve updated
            stmt_get = select(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == group_id,
            )
            result = await session.execute(stmt_get)
            return result.scalar_one_or_none()

    async def delete_group(self, user_id: int, group_id: str) -> bool:
        """Delete a task group and cascade delete all contained tasks."""
        async with self.session_manager.session() as session:
            # First cascade delete all tasks in the group
            stmt_tasks = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_list_id == group_id,
            )
            await session.execute(stmt_tasks)

            # Then delete the group itself
            stmt_group = delete(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == group_id,
            )
            result = await session.execute(stmt_group)
            await session.commit()

            return bool(getattr(result, "rowcount", 0) > 0)

    async def clear_group_tasks(self, user_id: int, group_id: str) -> bool:
        """Clear all tasks from a task group without deleting the group."""
        async with self.session_manager.session() as session:
            stmt = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_list_id == group_id,
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(getattr(result, "rowcount", 0) > 0)

    # Task Operations

    async def create_task(
        self,
        user_id: int,
        group_id: str,
        title: str,
        detail: str = "",
        status: str = "needsAction",
        importance: str | None = None,
        due_time: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool = False,
        links: str | None = None,
        sort: int | None = None,
        sort_completed: int | None = None,
        planer_sort: int | None = None,
        all_sort: int | None = None,
        all_sort_completed: int | None = None,
        sort_time: int | None = None,
        planer_sort_time: int | None = None,
        all_sort_time: int | None = None,
        task_id: str | None = None,
    ) -> ScheduleTaskDO:
        """Create a new task."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        if len(detail) > MAX_DETAIL_LENGTH:
            raise ValueError("Detail is too long")
        async with self.session_manager.session() as session:
            kwargs: dict[str, Any] = {
                "user_id": user_id,
                "task_list_id": group_id,
                "title": title,
                "detail": detail,
                "status": status,
                "importance": importance,
                "due_time": due_time,
                "recurrence": recurrence,
                "is_reminder_on": is_reminder_on,
                "links": links,
                "sort": sort,
                "sort_completed": sort_completed,
                "planer_sort": planer_sort,
                "all_sort": all_sort,
                "all_sort_completed": all_sort_completed,
                "sort_time": sort_time,
                "planer_sort_time": planer_sort_time,
                "all_sort_time": all_sort_time,
            }
            if task_id is not None:
                kwargs["task_id"] = task_id
            task = ScheduleTaskDO(**kwargs)
            session.add(task)
            await session.flush()
            await session.commit()
            await session.refresh(task)
            return task

    async def get_task(self, user_id: int, task_id: str) -> ScheduleTaskDO | None:
        """Get a task by ID."""
        async with self.session_manager.session() as session:
            stmt = select(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_id == task_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_tasks(
        self,
        user_id: int,
        group_id: str | None = None,
        since: int | None = None,
    ) -> list[ScheduleTaskDO]:
        """List tasks for a user, optionally filtered by group and since timestamp."""
        async with self.session_manager.session() as session:
            query = select(ScheduleTaskDO).where(ScheduleTaskDO.user_id == user_id)
            if group_id is not None:
                query = query.where(ScheduleTaskDO.task_list_id == group_id)
            if since is not None:
                query = query.where(ScheduleTaskDO.update_time > since)

            query = query.order_by(ScheduleTaskDO.create_time.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_task(
        self, user_id: int, task_id: str, **kwargs: Any
    ) -> ScheduleTaskDO | None:
        """Update a task."""
        updates = {k: v for k, v in kwargs.items() if k in TASK_ALLOWED_UPDATE_FIELDS}
        updates["update_time"] = int(time.time() * 1000)

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

    async def batch_update_tasks(
        self, user_id: int, updates_list: list[dict[str, Any]]
    ) -> bool:
        """Batch update tasks atomically in a single transaction."""
        async with self.session_manager.session() as session:
            for item in updates_list:
                task_id = item.get("task_id")
                if not task_id:
                    continue
                title = item.get("title")
                if title is not None and len(title) > MAX_TITLE_LENGTH:
                    raise ValueError("Title is too long")
                detail = item.get("detail")
                if detail is not None and len(detail) > MAX_DETAIL_LENGTH:
                    raise ValueError("Detail is too long")

                updates = {
                    k: v
                    for k, v in item.items()
                    if k in TASK_ALLOWED_UPDATE_FIELDS and v is not None
                }
                if not updates:
                    continue

                stmt = (
                    update(ScheduleTaskDO)
                    .where(
                        ScheduleTaskDO.user_id == user_id,
                        ScheduleTaskDO.task_id == task_id,
                    )
                    .values(**updates)
                )
                res = await session.execute(stmt)
                if getattr(res, "rowcount", 0) == 0:
                    raise ValueError(f"Task {task_id} not found")
            await session.commit()
            return True

    async def delete_task(self, user_id: int, task_id: str) -> bool:
        """Delete a task."""
        async with self.session_manager.session() as session:
            stmt = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id, ScheduleTaskDO.task_id == task_id
            )
            result = cast(CursorResult[Any], await session.execute(stmt))
            await session.commit()
            return bool(result.rowcount > 0)
