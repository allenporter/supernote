"""Schedule and To-Do task management client (`ScheduleClient`).

This module provides `supernote.client.schedule.ScheduleClient` for managing task groups
(`create_group`, `list_groups`, `list_all_groups`, `delete_group`), individual and batch tasks
(`create_task`, `list_tasks`, `list_all_tasks`, `update_task`, `batch_update_tasks`, `delete_task`),
and RFC 5545 `.ics` calendar feeds (`get_ical_feed`). Request and response payloads are modeled in
`supernote.models.schedule`. See `supernote.client` and `supernote.guides.schedule_api` for details.
"""

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
    UpdateScheduleTaskListDTO,
    UpdateScheduleTaskVO,
)

from .client import Client

_UNSET = object()


class ScheduleClient:
    """Client for Schedule APIs using standard DTOs."""

    def __init__(self, client: Client):
        """Initialize a schedule client."""
        self._client = client

    async def create_group(
        self,
        title: str,
        task_list_id: str | None = None,
        create_time_ms: int | None = None,
        last_modified_ms: int | None = None,
    ) -> AddScheduleTaskGroupVO:
        """Create a new schedule group."""
        dto = AddScheduleTaskGroupDTO(
            title=title,
            task_list_id=task_list_id,
            create_time=create_time_ms,
            last_modified=last_modified_ms,
        )
        return await self._client.post_json(
            "/api/file/schedule/group", AddScheduleTaskGroupVO, json=dto.to_dict()
        )

    async def get_group(self, group_id: str) -> GetScheduleTaskGroupVO:
        """Get a schedule group by ID."""
        return await self._client.get_json(
            f"/api/file/schedule/group/{group_id}", GetScheduleTaskGroupVO
        )

    async def update_group(
        self,
        group_id: str,
        title: str,
        last_modified_ms: int | None = None,
    ) -> BaseResponse:
        """Update a schedule group."""
        dto = UpdateScheduleTaskGroupDTO(
            task_list_id=group_id,
            title=title,
            last_modified=(
                last_modified_ms
                if last_modified_ms is not None
                else int(time.time() * 1000)
            ),
        )
        return await self._client.put_json(
            "/api/file/schedule/group", BaseResponse, json=dto.to_dict()
        )

    async def clear_group(
        self, group_id: str, last_modified_ms: int | None = None
    ) -> BaseResponse:
        """Clear all tasks within a schedule group."""
        dto = ClearScheduleTaskGroupDTO(
            task_list_id=group_id, last_modified=last_modified_ms
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

    async def delete_group(self, group_id: str) -> None:
        """Delete a schedule group."""
        await self._client.request("delete", f"/api/file/schedule/group/{group_id}")

    async def create_task(
        self,
        group_id: str | None,
        title: str,
        detail: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        completed_time_ms: int | None = None,
        recurrence: str | None = None,
        is_reminder_on: bool = False,
        links: str | None = None,
        task_id: str | None = None,
        sort: int | None = None,
        sort_completed: int | None = None,
        planer_sort: int | None = None,
        all_sort: int | None = None,
    ) -> AddScheduleTaskVO:
        """Create a new schedule task."""
        dto = AddScheduleTaskDTO(
            task_id=task_id,
            task_list_id=group_id,
            title=title,
            detail=detail,
            status=status,
            importance=importance,
            due_time=due_time,
            completed_time=completed_time_ms,
            recurrence=recurrence,
            is_reminder_on=BooleanEnum.of(is_reminder_on),
            links=links,
            sort=sort,
            sort_completed=sort_completed,
            planer_sort=planer_sort,
            all_sort=all_sort,
        )
        return await self._client.post_json(
            "/api/file/schedule/task", AddScheduleTaskVO, json=dto.to_dict()
        )

    async def get_task(self, task_id: int | str) -> ScheduleTaskVO:
        """Get details for a single task."""
        return await self._client.get_json(
            f"/api/file/schedule/task/{task_id}", ScheduleTaskVO
        )

    async def get_tasks_all(
        self,
        group_id: str | None = None,
        next_sync_token: int | None = None,
        page_token: str | None = None,
    ) -> ScheduleTaskAllVO:
        """Fetch tasks response object including nextSyncToken and scheduleTask items."""
        dto = ScheduleTaskDTO(
            task_list_id=group_id,
            next_sync_token=next_sync_token,
            next_page_tokens=page_token,
        )
        return await self._client.post_json(
            "/api/file/schedule/task/all", ScheduleTaskAllVO, json=dto.to_dict()
        )

    async def list_tasks(
        self,
        group_id: str | None = None,
        since: int | None = None,
    ) -> AsyncIterator[ScheduleTaskInfo]:
        """List all schedule tasks, automatically iterating through all pages.

        Args:
            group_id: Optional task group ID to filter by.
            since: Optional nextSyncToken timestamp for incremental delta sync.

        Yields:
            ScheduleTaskInfo: A schedule task.
        """
        page_token = None
        while True:
            response = await self.get_tasks_all(
                group_id=group_id,
                next_sync_token=since,
                page_token=page_token,
            )
            for item in response.schedule_task:
                yield item

            page_token = response.next_page_token
            if not page_token:
                break

    async def update_task(
        self,
        task_id: str,
        title: str | None = None,
        detail: str | None | object = _UNSET,
        status: str | None = None,
        importance: str | None | object = _UNSET,
        due_time: int | None = None,
        completed_time_ms: int | None = None,
        recurrence: str | None | object = _UNSET,
        is_reminder_on: bool | None = None,
        links: str | None | object = _UNSET,
        task_list_id: str | None | object = _UNSET,
        last_modified_ms: int | None = None,
    ) -> UpdateScheduleTaskVO:
        """Update a task using DTO."""
        is_reminder_on_value: BooleanEnum | None = None
        if is_reminder_on is not None:
            is_reminder_on_value = BooleanEnum.of(is_reminder_on)

        dto = UpdateScheduleTaskDTO(
            task_id=task_id,
            title=title,
            detail=detail if isinstance(detail, str) else None,
            status=status,
            importance=importance if isinstance(importance, str) else None,
            due_time=due_time,
            completed_time=completed_time_ms,
            recurrence=recurrence if isinstance(recurrence, str) else None,
            is_reminder_on=is_reminder_on_value,
            links=links if isinstance(links, str) else None,
            task_list_id=task_list_id if isinstance(task_list_id, str) else None,
            last_modified=(
                last_modified_ms
                if last_modified_ms is not None
                else int(time.time() * 1000)
            ),
        )
        payload = dto.to_dict()
        for alias, value in (
            ("detail", detail),
            ("importance", importance),
            ("recurrence", recurrence),
            ("links", links),
            ("taskListId", task_list_id),
        ):
            if value is None:
                payload[alias] = None
        return await self._client.put_json(
            "/api/file/schedule/task",
            UpdateScheduleTaskVO,
            json=payload,
        )

    async def batch_update_tasks(
        self,
        tasks: list[UpdateScheduleTaskDTO],
        task_list_id: str | None = None,
    ) -> BaseResponse:
        """Batch update a list of schedule tasks."""
        dto = UpdateScheduleTaskListDTO(
            task_list_id=task_list_id,
            update_schedule_task_list=tasks,
        )
        return await self._client.put_json(
            "/api/file/schedule/task/list",
            BaseResponse,
            json=dto.to_dict(),
        )

    async def delete_task(self, task_id: str) -> None:
        """Delete a schedule task."""
        await self._client.request("delete", f"/api/file/schedule/task/{task_id}")

    async def get_ical_feed(self, group_id: str | None = None) -> str:
        """Get the iCalendar (.ics) feed for the user's tasks.

        Args:
            group_id: Optional task list group ID to filter by.

        Returns:
            str: RFC 5545 iCalendar (.ics) text stream.
        """
        params: dict[str, str] = {}
        if group_id is not None:
            params["taskListId"] = group_id

        resp = await self._client.request(
            "get", "/api/schedule/feed.ics", params=params
        )
        return await resp.text()
