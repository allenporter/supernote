import hashlib
import logging
import time
from dataclasses import fields
from typing import Any

from aiohttp import web

from supernote.models.base import BaseResponse, BooleanEnum
from supernote.models.schedule import (
    AddScheduleTaskDTO,
    AddScheduleTaskGroupDTO,
    AddScheduleTaskGroupVO,
    AddScheduleTaskVO,
    ClearScheduleTaskGroupDTO,
    GetScheduleSortVO,
    GetScheduleTaskGroupVO,
    ScheduleTaskAllVO,
    ScheduleTaskDTO,
    ScheduleTaskGroupItem,
    ScheduleTaskGroupVO,
    ScheduleTaskInfo,
    ScheduleTaskVO,
    UpdateScheduleTaskDTO,
    UpdateScheduleTaskGroupDTO,
    UpdateScheduleTaskListDTO,
    UpdateScheduleTaskVO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.services.ical_export import ICalExportService
from supernote.server.services.schedule import ScheduleService

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


def _parse_id_to_int(val: Any) -> int:
    """Safely parse integer ID or deterministically convert string UUID to integer ID."""
    if isinstance(val, int):
        return val
    if not val:
        return 0
    val_str = str(val).strip()
    if val_str.isdigit() or (val_str.startswith("-") and val_str[1:].isdigit()):
        return int(val_str)
    return int(hashlib.md5(val_str.encode("utf-8")).hexdigest()[:15], 16) & 0x7FFFFFFFFFFFFFFF


def _extract_task_updates(dto: UpdateScheduleTaskDTO) -> dict[str, Any]:
    """Extract populated update fields from UpdateScheduleTaskDTO into a service dict."""
    updates: dict[str, Any] = {}
    for f in fields(dto):
        if f.name in ("task_id", "last_modified", "is_deleted"):
            continue
        val = getattr(dto, f.name)
        if val is not None:
            if f.name == "task_list_id":
                updates["task_list_id"] = _parse_id_to_int(val)
            elif f.name == "is_reminder_on":
                updates["is_reminder_on"] = val == BooleanEnum.YES
            else:
                updates[f.name] = val
    return updates


@routes.post("/api/file/schedule/group")
async def create_group(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = AddScheduleTaskGroupDTO.from_dict(data)
        if not dto.title:
            raise SupernoteError("Title required", status_code=400)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        group = await schedule_service.create_group(user_id, dto.title)
        return web.json_response(
            AddScheduleTaskGroupVO(
                success=True, task_list_id=str(group.task_list_id)
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except ValueError as err:
        return SupernoteError(str(err), status_code=400).to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/schedule/group")
async def update_group(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = UpdateScheduleTaskGroupDTO.from_dict(data)
        if not dto.task_list_id or not dto.title:
            raise SupernoteError("Missing required fields", status_code=400)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        group = await schedule_service.update_group(
            user_id, _parse_id_to_int(dto.task_list_id), dto.title
        )
        if not group:
            raise SupernoteError("Not found", status_code=404)
        return web.json_response(BaseResponse(success=True).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except ValueError as err:
        return SupernoteError(str(err), status_code=400).to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.delete("/api/file/schedule/group/{taskListId}")
async def delete_group(request: web.Request) -> web.Response:
    try:
        group_id_str = request.match_info.get("taskListId")
        if not group_id_str:
            raise SupernoteError("Missing taskListId", status_code=400)

        group_id = _parse_id_to_int(group_id_str)
        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        success = await schedule_service.delete_group(user_id, group_id)
        if not success:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(BaseResponse(success=True).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/file/schedule/group/{taskListId}")
async def get_group(request: web.Request) -> web.Response:
    try:
        group_id_str = request.match_info.get("taskListId")
        if not group_id_str:
            raise SupernoteError("Missing taskListId", status_code=400)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        group = await schedule_service.get_group(user_id, _parse_id_to_int(group_id_str))
        if not group:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(
            GetScheduleTaskGroupVO(
                success=True,
                task_list_id=str(group.task_list_id),
                user_id=group.user_id,
                title=group.title,
                create_time=group.create_time,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/schedule/group/clear")
async def clear_group(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = ClearScheduleTaskGroupDTO.from_dict(data)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        await schedule_service.clear_group_tasks(user_id, _parse_id_to_int(dto.task_list_id))
        return web.json_response(BaseResponse(success=True).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/schedule/group/all")
async def list_groups(request: web.Request) -> web.Response:
    try:
        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        groups = await schedule_service.list_groups(user_id)

        items = [
            ScheduleTaskGroupItem(
                task_list_id=str(g.task_list_id),
                user_id=g.user_id,
                title=g.title,
                last_modified=g.create_time,
                is_deleted=BooleanEnum.NO,
                create_time=g.create_time,
            )
            for g in groups
        ]

        return web.json_response(
            ScheduleTaskGroupVO(success=True, schedule_task_group=items).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/schedule/task")
async def create_task(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = AddScheduleTaskDTO.from_dict(data)

        if not dto.title:
            raise SupernoteError("Title is required", status_code=400)

        group_id = _parse_id_to_int(dto.task_list_id) if dto.task_list_id else 0

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        task = await schedule_service.create_task(
            user_id=user_id,
            group_id=group_id,
            title=dto.title,
            detail=dto.detail or "",
            status=dto.status or "needsAction",
            importance=dto.importance,
            due_time=dto.due_time,
            is_reminder_on=(
                dto.is_reminder_on == BooleanEnum.YES if dto.is_reminder_on else False
            ),
            links=dto.links,
            sort=dto.sort,
            sort_completed=dto.sort_completed,
            planer_sort=dto.planer_sort,
            all_sort=dto.all_sort,
            all_sort_completed=dto.all_sort_completed,
            sort_time=dto.sort_time,
            planer_sort_time=dto.planer_sort_time,
            all_sort_time=dto.all_sort_time,
            task_id=_parse_id_to_int(dto.task_id) if dto.task_id else None,
        )
        task_id_resp = str(task.task_id)
        return web.json_response(
            AddScheduleTaskVO(success=True, task_id=task_id_resp).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except ValueError as err:
        return SupernoteError(str(err), status_code=400).to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/schedule/task")
async def update_task(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = UpdateScheduleTaskDTO.from_dict(data)
        if not dto.task_id:
            raise SupernoteError("Missing taskId", status_code=400)

        task_id = _parse_id_to_int(dto.task_id)
        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        updates = _extract_task_updates(dto)
        updated_task = await schedule_service.update_task(user_id, task_id, **updates)
        if not updated_task:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(
            UpdateScheduleTaskVO(
                success=True, task_id=str(updated_task.task_id)
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/schedule/task/list")
async def batch_update_task_list(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        dto = UpdateScheduleTaskListDTO.from_dict(data)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        updates_list: list[dict[str, Any]] = []
        for item in dto.update_schedule_task_list:
            if item.task_id:
                item_updates = _extract_task_updates(item)
                item_updates["task_id"] = _parse_id_to_int(item.task_id)
                updates_list.append(item_updates)

        await schedule_service.batch_update_tasks(user_id, updates_list)
        return web.json_response(BaseResponse(success=True).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except ValueError as err:
        return SupernoteError(str(err), status_code=400).to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.delete("/api/file/schedule/task/{taskId}")
async def delete_task(request: web.Request) -> web.Response:
    try:
        task_id_str = request.match_info.get("taskId")
        if not task_id_str:
            raise SupernoteError("Missing taskId", status_code=400)

        task_id = _parse_id_to_int(task_id_str)
        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        success = await schedule_service.delete_task(user_id, task_id)
        if not success:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(BaseResponse(success=True).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/file/schedule/task/{taskId}")
async def get_task(request: web.Request) -> web.Response:
    try:
        task_id_str = request.match_info.get("taskId")
        if not task_id_str:
            raise SupernoteError("Missing taskId", status_code=400)

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        task = await schedule_service.get_task(user_id, _parse_id_to_int(task_id_str))
        if not task:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(
            ScheduleTaskVO(
                success=True,
                task_id=str(task.task_id),
                task_list_id=str(task.task_list_id),
                title=task.title,
                detail=task.detail,
                status=task.status,
                importance=task.importance,
                due_time=task.due_time,
                recurrence=task.recurrence,
                is_reminder_on=(
                    BooleanEnum.YES if task.is_reminder_on else BooleanEnum.NO
                ),
                links=task.links,
                sort=task.sort,
                sort_completed=task.sort_completed,
                planer_sort=task.planer_sort,
                all_sort=task.all_sort,
                all_sort_completed=task.all_sort_completed,
                sort_time=task.sort_time,
                planer_sort_time=task.planer_sort_time,
                all_sort_time=task.all_sort_time,
                last_modified=task.update_time,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/schedule/task/all")
async def list_tasks(request: web.Request) -> web.Response:
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        dto = ScheduleTaskDTO.from_dict(data)
        group_id = _parse_id_to_int(dto.task_list_id) if dto.task_list_id else None

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        # Capture sync_start_time before querying to prevent missing concurrent updates.
        # Note: Backdated timestamps from clock drift or offline devices can cause delta sync races;
        # production systems resolve this via a monotonically increasing sequence counter (logical clock).
        sync_start_time = int(time.time() * 1000)

        tasks_dos = await schedule_service.list_tasks(
            user_id, group_id, since=dto.next_sync_token
        )

        tasks_vos = [
            ScheduleTaskInfo(
                task_id=str(t.task_id),
                task_list_id=str(t.task_list_id),
                title=t.title,
                detail=t.detail,
                status=t.status,
                importance=t.importance,
                due_time=t.due_time or 0,
                completed_time=t.completed_time or 0,
                recurrence=t.recurrence,
                is_reminder_on=(
                    BooleanEnum.YES if t.is_reminder_on else BooleanEnum.NO
                ),
                is_deleted=BooleanEnum.NO,
                links=t.links,
                sort=t.sort if t.sort is not None else 0,
                sort_completed=t.sort_completed if t.sort_completed is not None else 0,
                planer_sort=t.planer_sort if t.planer_sort is not None else 0,
                all_sort=t.all_sort,
                all_sort_completed=t.all_sort_completed,
                sort_time=t.sort_time or t.update_time or 0,
                planer_sort_time=t.planer_sort_time or 0,
                all_sort_time=t.all_sort_time,
                last_modified=t.update_time,
            )
            for t in tasks_dos
        ]

        return web.json_response(
            ScheduleTaskAllVO(
                success=True,
                schedule_task=tasks_vos,
                next_sync_token=sync_start_time,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/schedule/sort")
async def add_sort(request: web.Request) -> web.Response:
    return web.json_response(BaseResponse(success=True).to_dict())


@routes.put("/api/file/schedule/sort")
async def update_sort(request: web.Request) -> web.Response:
    return web.json_response(BaseResponse(success=True).to_dict())


@routes.delete("/api/file/schedule/sort/{taskListId}")
async def delete_sort(request: web.Request) -> web.Response:
    return web.json_response(BaseResponse(success=True).to_dict())


@routes.post("/api/file/query/schedule/sort")
async def get_sort(request: web.Request) -> web.Response:
    return web.json_response(GetScheduleSortVO(success=True).to_dict())


@routes.get("/api/schedule/feed.ics")
async def get_schedule_feed_ics(request: web.Request) -> web.Response:
    """Export schedule tasks as RFC 5545 iCalendar VTODO feed (.ics)."""
    user_email = request["user"]
    user_service = request.app["user_service"]
    user_id = await user_service.get_user_id(user_email)

    task_list_id_str = request.query.get("taskListId")
    task_list_id = (
        _parse_id_to_int(task_list_id_str)
        if task_list_id_str
        else None
    )

    schedule_service: ScheduleService = request.app["schedule_service"]
    ical_export_service = ICalExportService(
        request.app["session_manager"], schedule_service
    )

    ics_content = await ical_export_service.export_calendar(
        user_id, task_list_id=task_list_id
    )

    return web.Response(
        body=ics_content.encode("utf-8"),
        content_type="text/calendar",
        charset="utf-8",
        headers={
            "Content-Disposition": 'inline; filename="feed.ics"',
        },
    )
