import time
from typing import Any, AsyncIterator, Optional

from supernote.models.base import BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskDTO,
    AddScheduleTaskGroupDTO,
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ScheduleTaskAllVO,
    ScheduleTaskGroupItem,
    ScheduleTaskGroupVO,
    ScheduleTaskInfo,
    UpdateScheduleTaskDTO,
    UpdateScheduleTaskVO,
)

from . import Client


class ScheduleClient:
    """Client for Schedule APIs using standard DTOs."""

    def __init__(self, client: Client):
        """Initialize a schedule client."""
        self._client = client

    async def create_group(self, title: str) -> AddScheduleTaskGroupVO:
        """Create a new schedule group."""
        dto = AddScheduleTaskGroupDTO(title=title)
        return await self._client.post_json(
            "/api/schedule/groups", AddScheduleTaskGroupVO, json=dto.to_dict()
        )

    async def list_groups(self) -> AsyncIterator[ScheduleTaskGroupItem]:
        """List all schedule groups.

        This is a generator that yields groups one by one. It pages
        through the results and yields each group as it is received.

        Yields:
            ScheduleTaskGroupItem: A schedule group.
        """
        page_token = None
        while True:
            params: dict[str, Any] = {}
            if page_token:
                params["pageToken"] = page_token

            response = await self._client.get_json(
                "/api/schedule/groups", ScheduleTaskGroupVO, params=params
            )

            for item in response.schedule_task_group:
                yield item

            page_token = response.page_token
            if not page_token:
                break

    async def delete_group(self, group_id: int) -> None:
        """Delete a schedule group."""
        await self._client.request("delete", f"/api/schedule/groups/{group_id}")

    async def create_task(
        self,
        group_id: int,
        title: str,
        detail: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool = False,
    ) -> AddScheduleTaskVO:
        """Create a new schedule task."""
        dto = AddScheduleTaskDTO(
            task_list_id=str(group_id),
            title=title,
            detail=detail,
            status=status,
            importance=importance,
            due_time=due_time,
            recurrence=recurrence,
            is_reminder_on=BooleanEnum.of(is_reminder_on),
        )
        return await self._client.post_json(
            "/api/schedule/tasks", AddScheduleTaskVO, json=dto.to_dict()
        )

    async def list_tasks(
        self, group_id: Optional[int] = None
    ) -> AsyncIterator[ScheduleTaskInfo]:
        """List all schedule tasks."""
        next_page_tokens = None
        while True:
            params: dict[str, Any] = {}
            if group_id:
                params["taskListId"] = str(group_id)
            if next_page_tokens:
                params["nextPageTokens"] = next_page_tokens

            response = await self._client.get_json(
                "/api/schedule/tasks", ScheduleTaskAllVO, params=params
            )

            for item in response.schedule_task:
                yield item

            next_page_tokens = response.next_page_token
            if not next_page_tokens:
                break

    async def update_task(
        self,
        task_id: int,
        title: str,
        detail: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool | None = None,
        task_list_id: int | None = None,
    ) -> UpdateScheduleTaskVO:
        """Update a task using DTO."""
        is_reminder_on_value: BooleanEnum | None = None
        if is_reminder_on is not None:
            is_reminder_on_value = BooleanEnum.of(is_reminder_on)

        dto = UpdateScheduleTaskDTO(
            task_id=str(task_id),
            title=title,
            detail=detail,
            status=status,
            importance=importance,
            due_time=due_time,
            recurrence=recurrence,
            is_reminder_on=is_reminder_on_value,
            task_list_id=str(task_list_id) if task_list_id else None,
            last_modified=int(time.time() * 1000),
        )
        return await self._client.put_json(
            f"/api/schedule/tasks/{task_id}", UpdateScheduleTaskVO, json=dto.to_dict()
        )

    async def delete_task(self, task_id: int) -> None:
        """Delete a schedule task."""
        await self._client.request("delete", f"/api/schedule/tasks/{task_id}")
