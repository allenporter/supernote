"""Schedule and task management service for Supernote hardware and Web UI clients.

`ScheduleService` manages task groups (`ScheduleTaskGroupDO`) and tasks (`ScheduleTaskDO`),
enforcing client-supplied or server-generated IDs, atomic all-or-nothing batch updates,
cascade soft-deletes, and `nextSyncToken` delta queries. Mutations publish
`ScheduleUpdatedEvent` onto `supernote.server.events.LocalEventBus` for real-time Socket.IO
push notifications. Used by `supernote.server.routes.schedule` and
`supernote.server.services.ical_export.ICalExportService`. See `supernote.guides.schedule_api`.
"""

import logging
import time
from typing import Any, cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult

from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, ScheduleUpdatedEvent
from supernote.server.exceptions import TaskGroupNotFound

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
    "update_time",
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

TASK_NULLABLE_FIELDS: set[str] = {
    "task_list_id",
    "detail",
    "importance",
    "recurrence",
    "links",
}


class ScheduleService:
    """Schedule service."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        event_bus: LocalEventBus | None = None,
    ) -> None:
        """Initialize the schedule service."""
        self.session_manager = session_manager
        self.event_bus = event_bus

    async def _publish_schedule_updated(
        self,
        user_id: int,
        task_list_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(
                ScheduleUpdatedEvent(
                    user_id=user_id,
                    task_list_id=task_list_id,
                    task_id=task_id,
                )
            )

    # Task Group Operations

    async def create_group(
        self,
        user_id: int,
        title: str,
        task_list_id: str | None = None,
        create_time_ms: int | None = None,
        last_modified_ms: int | None = None,
    ) -> ScheduleTaskGroupDO:
        """Create a new task group."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        now_ms = int(time.time() * 1000)
        created_ms = (
            create_time_ms
            if create_time_ms is not None
            else (last_modified_ms if last_modified_ms is not None else now_ms)
        )
        updated_ms = last_modified_ms if last_modified_ms is not None else created_ms

        async with self.session_manager.session() as session:
            kwargs: dict[str, Any] = {
                "user_id": user_id,
                "title": title,
                "create_time": created_ms,
                "update_time": updated_ms,
            }
            if task_list_id is not None:
                kwargs["task_list_id"] = task_list_id
            group = ScheduleTaskGroupDO(**kwargs)
            session.add(group)
            # Flush to generate ID
            await session.flush()
            await session.commit()
            await session.refresh(group)

        await self._publish_schedule_updated(
            user_id=user_id, task_list_id=group.task_list_id
        )
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
        self,
        user_id: int,
        group_id: str,
        title: str,
        last_modified_ms: int | None = None,
    ) -> ScheduleTaskGroupDO | None:
        """Update a task group title."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        now_ms = int(time.time() * 1000)
        async with self.session_manager.session() as session:
            if not (group := await self.get_group(user_id, group_id)):
                return None

            prev_time = group.update_time or group.create_time or 0
            updated_ms = (
                last_modified_ms
                if last_modified_ms is not None
                else max(now_ms, prev_time + 1)
            )
            stmt = (
                update(ScheduleTaskGroupDO)
                .where(
                    ScheduleTaskGroupDO.user_id == user_id,
                    ScheduleTaskGroupDO.task_list_id == group.task_list_id,
                )
                .values(title=title, update_time=updated_ms)
                .execution_options(synchronize_session="fetch")
            )
            await session.execute(stmt)
            await session.commit()

            # Retrieve updated
            stmt_get = select(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == group.task_list_id,
            )
            result = await session.execute(stmt_get)
            updated_group = result.scalar_one_or_none()

        if updated_group is not None:
            await self._publish_schedule_updated(
                user_id=user_id, task_list_id=updated_group.task_list_id
            )
        return updated_group

    async def delete_group(self, user_id: int, group_id: str) -> bool:
        """Delete a task group and cascade delete all contained tasks."""
        async with self.session_manager.session() as session:
            if not (group := await self.get_group(user_id, group_id)):
                return False

            target_group_id = group.task_list_id
            # First cascade delete all tasks in the group
            stmt_tasks = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_list_id == target_group_id,
            )
            await session.execute(stmt_tasks)

            # Then delete the group itself
            stmt_group = delete(ScheduleTaskGroupDO).where(
                ScheduleTaskGroupDO.user_id == user_id,
                ScheduleTaskGroupDO.task_list_id == target_group_id,
            )
            result = await session.execute(stmt_group)
            await session.commit()
            deleted = bool(getattr(result, "rowcount", 0) > 0)

        if deleted:
            await self._publish_schedule_updated(
                user_id=user_id, task_list_id=target_group_id
            )
        return deleted

    async def clear_group_tasks(self, user_id: int, group_id: str) -> bool:
        """Clear all tasks from a task group without deleting the group."""
        async with self.session_manager.session() as session:
            if not (group := await self.get_group(user_id, group_id)):
                return False

            target_group_id = group.task_list_id
            # Clear all tasks from the group without deleting the group
            stmt = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_list_id == target_group_id,
            )
            result = await session.execute(stmt)
            await session.commit()
            cleared = bool(getattr(result, "rowcount", 0) > 0)

        if cleared:
            await self._publish_schedule_updated(
                user_id=user_id, task_list_id=target_group_id
            )
        return cleared

    # Task Operations

    async def create_task(
        self,
        user_id: int,
        group_id: str | None = None,
        title: str = "",
        detail: str = "",
        status: str = "needsAction",
        importance: str | None = None,
        due_time: int | None = None,
        completed_time_ms: int | None = None,
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
        last_modified_ms: int | None = None,
    ) -> ScheduleTaskDO:
        """Create a new task."""
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError("Title is too long")
        if len(detail) > MAX_DETAIL_LENGTH:
            raise ValueError("Detail is too long")
        if group_id is not None:
            if not group_id or not await self.get_group(user_id, group_id):
                raise TaskGroupNotFound(f"Task group {group_id} does not exist")
        async with self.session_manager.session() as session:
            kwargs: dict[str, Any] = {
                "user_id": user_id,
                "task_list_id": group_id,
                "title": title,
                "detail": detail,
                "status": status,
                "importance": importance,
                "due_time": due_time,
                "completed_time": completed_time_ms,
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
            if last_modified_ms is not None:
                kwargs["update_time"] = last_modified_ms
            if task_id is not None:
                kwargs["task_id"] = task_id

            task = ScheduleTaskDO(**kwargs)
            session.add(task)
            # Flush to generate ID
            await session.flush()
            await session.commit()
            await session.refresh(task)

        await self._publish_schedule_updated(
            user_id=user_id,
            task_list_id=task.task_list_id,
            task_id=task.task_id,
        )
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
                query = query.where(
                    or_(
                        ScheduleTaskDO.update_time > since,
                        ScheduleTaskDO.sort_time > since,
                        ScheduleTaskDO.planer_sort_time > since,
                    )
                )

            query = query.order_by(ScheduleTaskDO.create_time.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_task(
        self, user_id: int, task_id: str, **kwargs: Any
    ) -> ScheduleTaskDO | None:
        """Update a task."""
        updates = {k: v for k, v in kwargs.items() if k in TASK_ALLOWED_UPDATE_FIELDS}
        if (target_group_id := updates.get("task_list_id")) is not None:
            if not target_group_id or not await self.get_group(
                user_id, target_group_id
            ):
                raise TaskGroupNotFound(f"Task group {target_group_id} does not exist")
        if not updates.get("update_time"):
            updates["update_time"] = int(time.time() * 1000)

        async with self.session_manager.session() as session:
            if not (task := await self.get_task(user_id, task_id)):
                return None

            stmt = (
                update(ScheduleTaskDO)
                .where(
                    ScheduleTaskDO.user_id == user_id,
                    ScheduleTaskDO.task_id == task.task_id,
                )
                .values(**updates)
                .execution_options(synchronize_session="fetch")
            )
            await session.execute(stmt)
            await session.commit()

            # Retrieve updated
            stmt_get = select(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_id == task.task_id,
            )
            result = await session.execute(stmt_get)
            updated_task = result.scalar_one_or_none()

        if updated_task is not None:
            await self._publish_schedule_updated(
                user_id=user_id,
                task_list_id=updated_task.task_list_id,
                task_id=updated_task.task_id,
            )
        return updated_task

    async def batch_update_tasks(
        self,
        user_id: int,
        updates_list: list[dict[str, Any]],
        task_list_id: str | None = None,
    ) -> bool:
        """Batch update tasks atomically in a single transaction."""
        now_ms = int(time.time() * 1000)
        resolved_group_id = task_list_id
        updated_any = False
        async with self.session_manager.session() as session:
            for item in updates_list:
                if not (task_id := item.get("task_id")):
                    continue
                if (title := item.get("title")) is not None and len(
                    title
                ) > MAX_TITLE_LENGTH:
                    raise ValueError("Title is too long")
                if (detail := item.get("detail")) is not None and len(
                    detail
                ) > MAX_DETAIL_LENGTH:
                    raise ValueError("Detail is too long")
                if (target_group_id := item.get("task_list_id")) is not None:
                    if not target_group_id or not await self.get_group(
                        user_id, target_group_id
                    ):
                        raise TaskGroupNotFound(
                            f"Task group {target_group_id} does not exist"
                        )

                if not (task := await self.get_task(user_id, str(task_id))):
                    raise ValueError(f"Task {task_id} not found")

                if resolved_group_id is None and task.task_list_id is not None:
                    resolved_group_id = task.task_list_id

                updates = {
                    k: v
                    for k, v in item.items()
                    if k in TASK_ALLOWED_UPDATE_FIELDS
                    and (v is not None or k in TASK_NULLABLE_FIELDS)
                }
                if not updates:
                    continue
                if not updates.get("update_time"):
                    updates["update_time"] = now_ms

                stmt = (
                    update(ScheduleTaskDO)
                    .where(
                        ScheduleTaskDO.user_id == user_id,
                        ScheduleTaskDO.task_id == task.task_id,
                    )
                    .values(**updates)
                )
                await session.execute(stmt)
                updated_any = True
            await session.commit()

        if updated_any:
            await self._publish_schedule_updated(
                user_id=user_id, task_list_id=resolved_group_id
            )
        return True

    async def delete_task(self, user_id: int, task_id: str) -> bool:
        """Delete a task."""
        async with self.session_manager.session() as session:
            if not (task := await self.get_task(user_id, task_id)):
                return False

            target_group_id = task.task_list_id
            target_task_id = task.task_id
            stmt = delete(ScheduleTaskDO).where(
                ScheduleTaskDO.user_id == user_id,
                ScheduleTaskDO.task_id == target_task_id,
            )
            result = cast(CursorResult[Any], await session.execute(stmt))
            await session.commit()
            deleted = bool(result.rowcount > 0)

        if deleted:
            await self._publish_schedule_updated(
                user_id=user_id,
                task_list_id=target_group_id,
                task_id=target_task_id,
            )
        return deleted
