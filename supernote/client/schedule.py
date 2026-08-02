import time
from collections.abc import AsyncIterator

from supernote.models.base import BaseResponse, BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskDTO,
    AddScheduleTaskGroupDTO,
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ClearScheduleTaskGroupDTO,
    GetScheduleTaskGroupVO,
    ScheduleTaskAllVO,
    ScheduleTaskDTO,
    ScheduleTaskGroupDTO,
    ScheduleTaskGroupItem,
    ScheduleTaskGroupVO,
    ScheduleTaskInfo,
    ScheduleTaskVO,
    UpdateScheduleTaskDTO,
    UpdateScheduleTaskGroupDTO,
    UpdateScheduleTaskVO,
)

from .client import Client


class ScheduleClient:
    """Client for Schedule APIs using standard DTOs."""

    def __init__(self, client: Client):
        """Initialize a schedule client."""
        self._client = client

    async def create_group(self, title: str) -> AddScheduleTaskGroupVO:
        """Create a new schedule group."""
        dto = AddScheduleTaskGroupDTO(title=title)
        return await self._client.post_json(
            "/api/file/schedule/group", AddScheduleTaskGroupVO, json=dto.to_dict()
        )

    async def get_group(self, group_id: int) -> GetScheduleTaskGroupVO:
        """Get a schedule group by ID."""
        return await self._client.get_json(
            f"/api/file/schedule/group/{group_id}", GetScheduleTaskGroupVO
        )

    async def update_group(self, group_id: int, title: str) -> BaseResponse:
        """Update a schedule group."""
        dto = UpdateScheduleTaskGroupDTO(
            task_list_id=str(group_id),
            title=title,
            last_modified=int(time.time() * 1000),
        )
        return await self._client.put_json(
            "/api/file/schedule/group", BaseResponse, json=dto.to_dict()
        )

    async def clear_group(self, group_id: int) -> BaseResponse:
        """Clear all tasks within a schedule group."""
        dto = ClearScheduleTaskGroupDTO(
            task_list_id=str(group_id), last_modified=int(time.time() * 1000)
        )
        return await self._client.post_json(
            "/api/file/schedule/group/clear", BaseResponse, json=dto.to_dict()
        )

    async def list_groups(self) -> AsyncIterator[ScheduleTaskGroupItem]:
        """List all schedule groups.

        This is a generator that yields groups one by one. It pages
        through the results using pageToken and yields each group as it is received.

        Yields:
            ScheduleTaskGroupItem: A schedule group.
        """
        page_token = None
        while True:
            dto = ScheduleTaskGroupDTO(page_token=page_token)
            response = await self._client.post_json(
                "/api/file/schedule/group/all", ScheduleTaskGroupVO, json=dto.to_dict()
            )

            for item in response.schedule_task_group:
                yield item

            page_token = response.page_token
            if not page_token:
                break

    async def delete_group(self, group_id: int) -> None:
        """Delete a schedule group."""
        await self._client.request("delete", f"/api/file/schedule/group/{group_id}")

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
            "/api/file/schedule/task", AddScheduleTaskVO, json=dto.to_dict()
        )

    async def get_task(self, task_id: int) -> ScheduleTaskVO:
        """Get details for a single task."""
        return await self._client.get_json(
            f"/api/file/schedule/task/{task_id}", ScheduleTaskVO
        )

    async def list_tasks(
        self, group_id: int | None = None
    ) -> AsyncIterator[ScheduleTaskInfo]:
        """List all schedule tasks.

        This is a generator that yields tasks one by one. It pages
        through the results using nextPageTokens and yields each task
        as it is received.

        Yields:
            ScheduleTaskInfo: A schedule task.
        """
        page_token = None
        while True:
            dto = ScheduleTaskDTO(
                task_list_id=str(group_id) if group_id else None,
                next_page_tokens=page_token,
            )
            response = await self._client.post_json(
                "/api/file/schedule/task/all", ScheduleTaskAllVO, json=dto.to_dict()
            )

            for item in response.schedule_task:
                yield item

            page_token = response.next_page_token
            if not page_token:
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
            "/api/file/schedule/task", UpdateScheduleTaskVO, json=dto.to_dict()
        )

    async def delete_task(self, task_id: int) -> None:
        """Delete a schedule task."""
        await self._client.request("delete", f"/api/file/schedule/task/{task_id}")
