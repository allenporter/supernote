"""MCP platform setup exposing schedule task CRUD tools (`list_tasks`, `create_task`, `update_task`, `delete_task`)."""

from __future__ import annotations

import binascii
import logging
import time
from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.core import ServerCore
from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO
from supernote.server.events import bind_event_provenance
from supernote.server.exceptions import TaskGroupNotFound

from .service import SCHEDULE_SERVICE_KEY, ScheduleService

__all__ = ["async_setup_mcp"]

logger = logging.getLogger(__name__)

_VALID_TASK_STATUSES: frozenset[str] = frozenset({"needsAction", "completed"})
_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


def _decode_task_link(links_b64: str | None) -> ScheduleTaskLinkDTO | None:
    """Decode a Supernote task deep-link (`ScheduleTaskDO.links`), returning `None` on failure.

    A task link is a Base64-encoded JSON `ScheduleTaskLinkDTO` tying a To-Do task
    back to a specific notebook file and page (`fileId`, `filePath`, 1-indexed
    `page`, and `pageId`) so tablets and the Web UI can jump straight to the
    source page where the task originated.
    """
    if not links_b64:
        return None
    try:
        return ScheduleTaskLinkDTO.from_b64(links_b64)
    except (ValueError, TypeError, binascii.Error) as err:
        logger.warning("Failed to decode task link base64: %s", err)
        return None


def _encode_task_link(
    *,
    existing_links_b64: str | None = None,
    linked_file_id: str | None = None,
    linked_file_path: str | None = None,
    linked_page_id: str | None = None,
    linked_page_number: int | None = None,
    task_title: str | None = None,
) -> str | None:
    """Build or merge a `ScheduleTaskLinkDTO` and return its Base64 JSON encoding."""
    if all(
        v is None
        for v in (
            linked_file_id,
            linked_file_path,
            linked_page_id,
            linked_page_number,
        )
    ):
        return None

    existing = _decode_task_link(existing_links_b64)
    dto = ScheduleTaskLinkDTO(
        app_name=existing.app_name if existing else "Note",
        path=(
            linked_file_path
            if linked_file_path is not None
            else (existing.path if existing else "")
        ),
        page=(
            linked_page_number
            if linked_page_number is not None
            else (existing.page if existing else 1)
        ),
        file_id=(
            linked_file_id
            if linked_file_id is not None
            else (existing.file_id if existing else None)
        ),
        page_id=(
            linked_page_id
            if linked_page_id is not None
            else (existing.page_id if existing else None)
        ),
        task_title=(
            task_title
            if task_title is not None
            else (existing.task_title if existing else None)
        ),
    )
    return dto.to_b64()


def _serialize_group(group: ScheduleTaskGroupDO) -> dict[str, Any]:
    return {
        "group_id": group.task_list_id,
        "title": group.title,
        "create_time": group.create_time,
        "update_time": group.update_time,
    }


def _serialize_task(task: ScheduleTaskDO) -> dict[str, Any]:
    link = _decode_task_link(task.links)
    return {
        "task_id": task.task_id,
        "group_id": task.task_list_id,
        "title": task.title,
        "detail": task.detail,
        "status": task.status,
        "importance": task.importance,
        "due_time": task.due_time,
        "completed_time": task.completed_time,
        "recurrence": task.recurrence,
        "create_time": task.create_time,
        "update_time": task.update_time,
        "link": link.to_dict() if link is not None else None,
    }


def _validate_status(status: str | None) -> str | None:
    if status is not None and status not in _VALID_TASK_STATUSES:
        return (
            f"Invalid status {status!r}; expected one of: "
            f"{', '.join(sorted(_VALID_TASK_STATUSES))}."
        )
    return None


def _validate_page_number(page_number: int | None) -> str | None:
    if page_number is not None and page_number < 1:
        return "linked_page_number must be >= 1."
    return None


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register schedule task CRUD tools onto the MCP platform registrar."""
    schedule_service: ScheduleService = core.app[SCHEDULE_SERVICE_KEY]

    async def list_tasks(
        ctx: Context,
        group_id: str | None = None,
        include_completed: bool = False,
        file_id: str | None = None,
    ) -> dict[str, Any]:
        """List Supernote task groups and tasks, with optional group, status, and linked notebook filters.

        Args:
            group_id: Optional task group (`task_list_id`) to filter tasks by.
            include_completed: Include completed tasks when True (default: False).
            file_id: Optional linked notebook `file_id` to filter tasks by.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        groups = await schedule_service.list_groups(user_id)
        tasks = await schedule_service.list_tasks(user_id, group_id=group_id)

        serialized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            if not include_completed and task.status == "completed":
                continue
            item = _serialize_task(task)
            if file_id is not None:
                link = item["link"]
                link_file_id = link.get("fileId") if link else None
                if link_file_id is None or str(link_file_id) != str(file_id):
                    continue
            serialized_tasks.append(item)

        return {
            "success": True,
            "groups": [_serialize_group(g) for g in groups],
            "tasks": serialized_tasks,
        }

    async def create_task(
        ctx: Context,
        title: str,
        detail: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        group_id: str | None = None,
        linked_file_id: str | None = None,
        linked_file_path: str | None = None,
        linked_page_id: str | None = None,
        linked_page_number: int | None = None,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create a Supernote To-Do task with optional notebook page deep-link and event provenance.

        Args:
            title: Task title (required, non-empty).
            detail: Optional task notes/details.
            status: Task status ('needsAction' or 'completed'; default: 'needsAction').
            importance: Optional importance level (e.g. 'high').
            due_time: Optional due timestamp in Unix epoch milliseconds.
            group_id: Optional task group ID (`task_list_id`).
            linked_file_id: Optional linked notebook 64-bit file ID string.
            linked_file_path: Optional linked notebook path (e.g. '/Note/Planner.note').
            linked_page_id: Optional linked page GUID.
            linked_page_number: Optional 1-indexed page number in the linked notebook.
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for creating the task.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if not title or not title.strip():
            return create_error_response(
                "Task title must be non-empty.", ErrorCode.BAD_REQUEST
            ).to_dict()
        if err := _validate_status(status) or _validate_page_number(linked_page_number):
            return create_error_response(err, ErrorCode.BAD_REQUEST).to_dict()

        effective_status = status or "needsAction"
        normalized_due_time = None if due_time == 0 else due_time
        completed_time_ms = (
            int(time.time() * 1000) if effective_status == "completed" else None
        )
        links = _encode_task_link(
            linked_file_id=linked_file_id,
            linked_file_path=linked_file_path,
            linked_page_id=linked_page_id,
            linked_page_number=linked_page_number,
            task_title=title,
        )

        try:
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                task = await schedule_service.create_task(
                    user_id=user_id,
                    group_id=group_id,
                    title=title,
                    detail=detail or "",
                    status=effective_status,
                    importance=importance,
                    due_time=normalized_due_time,
                    completed_time_ms=completed_time_ms,
                    links=links,
                )
        except TaskGroupNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except ValueError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()

        return {"success": True, "task": _serialize_task(task)}

    async def update_task(
        ctx: Context,
        task_id: str,
        title: str | None = None,
        detail: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        due_time: int | None = None,
        group_id: str | None = None,
        linked_file_id: str | None = None,
        linked_file_path: str | None = None,
        linked_page_id: str | None = None,
        linked_page_number: int | None = None,
        clear_link: bool = False,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Partially update an existing Supernote To-Do task, including status, deep-link, and provenance.

        Args:
            task_id: ID of the task to update.
            title: Optional replacement task title.
            detail: Optional replacement task notes/details.
            status: Optional status ('needsAction' or 'completed').
            importance: Optional replacement importance level.
            due_time: Optional due timestamp in Unix epoch milliseconds (0 clears due_time).
            group_id: Optional target task group ID (`task_list_id`).
            linked_file_id: Optional linked notebook 64-bit file ID string.
            linked_file_path: Optional linked notebook path.
            linked_page_id: Optional linked page GUID.
            linked_page_number: Optional 1-indexed page number in the linked notebook.
            clear_link: When True, removes the task's notebook deep-link.
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for updating the task.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if title is not None and not title.strip():
            return create_error_response(
                "Task title must be non-empty.", ErrorCode.BAD_REQUEST
            ).to_dict()
        if err := _validate_status(status) or _validate_page_number(linked_page_number):
            return create_error_response(err, ErrorCode.BAD_REQUEST).to_dict()

        existing = await schedule_service.get_task(user_id, task_id)
        if existing is None:
            return create_error_response(
                f"Task {task_id} not found.", ErrorCode.NOT_FOUND
            ).to_dict()

        encoded_link = _encode_task_link(
            existing_links_b64=existing.links,
            linked_file_id=linked_file_id,
            linked_file_path=linked_file_path,
            linked_page_id=linked_page_id,
            linked_page_number=linked_page_number,
            task_title=title,
        )
        if clear_link and encoded_link is not None:
            return create_error_response(
                "Cannot combine clear_link=True with linked_* fields.",
                ErrorCode.BAD_REQUEST,
            ).to_dict()

        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if detail is not None:
            updates["detail"] = detail
        if importance is not None:
            updates["importance"] = importance
        if due_time is not None:
            updates["due_time"] = None if due_time == 0 else due_time
        if group_id is not None:
            updates["task_list_id"] = group_id
        if status is not None:
            updates["status"] = status
            if status == "completed":
                updates["completed_time"] = existing.completed_time or int(
                    time.time() * 1000
                )
            else:
                updates["completed_time"] = None

        if clear_link:
            updates["links"] = None
        elif encoded_link is not None:
            updates["links"] = encoded_link

        try:
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                updated = await schedule_service.update_task(
                    user_id, task_id, **updates
                )
        except TaskGroupNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except ValueError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()

        if updated is None:
            return create_error_response(
                f"Task {task_id} not found.", ErrorCode.NOT_FOUND
            ).to_dict()

        return {"success": True, "task": _serialize_task(updated)}

    async def delete_task(
        ctx: Context,
        task_id: str,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Delete a Supernote To-Do task by ID with user isolation and event provenance.

        Args:
            task_id: ID of the task to delete.
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for deleting the task.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        with bind_event_provenance(cause_seq=cause_seq, reason=reason):
            deleted = await schedule_service.delete_task(user_id, task_id)

        if not deleted:
            return create_error_response(
                f"Task {task_id} not found.", ErrorCode.NOT_FOUND
            ).to_dict()

        return {"success": True, "task_id": task_id}

    registrar.add_tool(list_tasks)
    registrar.add_tool(create_task)
    registrar.add_tool(update_task)
    registrar.add_tool(delete_task)
