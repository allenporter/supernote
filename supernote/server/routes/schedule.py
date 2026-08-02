import logging
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
from supernote.server.services.schedule import ScheduleService

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


def _extract_task_updates(dto: UpdateScheduleTaskDTO) -> dict[str, Any]:
    """Extract populated update fields from UpdateScheduleTaskDTO into a service dict."""
    updates: dict[str, Any] = {}
    for f in fields(dto):
        if f.name in ("task_id", "last_modified", "is_deleted"):
            continue
        val = getattr(dto, f.name)
        if val is not None:
            if f.name == "task_list_id":
                updates["task_list_id"] = int(val)
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
            user_id, int(dto.task_list_id), dto.title
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

        group_id = int(group_id_str)
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

        group = await schedule_service.get_group(user_id, int(group_id_str))
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

        await schedule_service.clear_group_tasks(user_id, int(dto.task_list_id))
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

        # Handle title gracefully
        title = dto.title or data.get("title") or "Untitled Task"

        # Handle group_id gracefully (default to 1 if task_list_id is missing or invalid)
        group_id = 1
        if dto.task_list_id:
            try:
                group_id = int(dto.task_list_id)
            except (ValueError, TypeError):
                group_id = 1

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        # Ensure at least one task group exists for the user
        groups = await schedule_service.list_groups(user_id)
        if not groups:
            await schedule_service.create_group(user_id, "Default")
            groups = await schedule_service.list_groups(user_id)

        if groups and group_id not in [g.task_list_id for g in groups]:
            group_id = groups[0].task_list_id

        task = await schedule_service.create_task(
            user_id=user_id,
            group_id=group_id,
            title=title,
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
        )
        task_id_resp = dto.task_id or str(task.task_id)
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

        task_id = int(dto.task_id)
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
                item_updates["task_id"] = int(item.task_id)
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

        task_id = int(task_id_str)
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

        task = await schedule_service.get_task(user_id, int(task_id_str))
        if not task:
            raise SupernoteError("Not found", status_code=404)

        return web.json_response(
            ScheduleTaskVO(
                success=True,
                task_id=task.task_id,
                task_list_id=task.task_list_id,
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
        group_id = None
        try:
            data = await request.json()
            dto = ScheduleTaskDTO.from_dict(data)
            if dto.task_list_id:
                group_id = int(dto.task_list_id)
        except Exception:
            pass

        user = request["user"]
        schedule_service: ScheduleService = request.app["schedule_service"]
        user_id = await request.app["user_service"].get_user_id(user)

        tasks_dos = await schedule_service.list_tasks(user_id, group_id)

        tasks_vos = [
            ScheduleTaskInfo(
                task_id=str(t.task_id),
                task_list_id=str(t.task_list_id),
                title=t.title,
                detail=t.detail,
                status=t.status,
                importance=t.importance,
                due_time=t.due_time,
                recurrence=t.recurrence,
                is_reminder_on=(
                    BooleanEnum.YES if t.is_reminder_on else BooleanEnum.NO
                ),
                links=t.links,
                sort=t.sort,
                sort_completed=t.sort_completed,
                planer_sort=t.planer_sort,
                all_sort=t.all_sort,
                all_sort_completed=t.all_sort_completed,
                sort_time=t.sort_time,
                planer_sort_time=t.planer_sort_time,
                all_sort_time=t.all_sort_time,
                last_modified=t.update_time,
            )
            for t in tasks_dos
        ]

        return web.json_response(
            ScheduleTaskAllVO(success=True, schedule_task=tasks_vos).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


# Placeholder Sort Endpoints (501 Not Implemented as requested for features pending backend support)
@routes.post("/api/file/schedule/sort")
async def add_sort(request: web.Request) -> web.Response:
    return SupernoteError("Not implemented", status_code=501).to_response()


@routes.put("/api/file/schedule/sort")
async def update_sort(request: web.Request) -> web.Response:
    return SupernoteError("Not implemented", status_code=501).to_response()


@routes.delete("/api/file/schedule/sort/{taskListId}")
async def delete_sort(request: web.Request) -> web.Response:
    return SupernoteError("Not implemented", status_code=501).to_response()


@routes.post("/api/file/query/schedule/sort")
async def get_sort(request: web.Request) -> web.Response:
    return SupernoteError("Not implemented", status_code=501).to_response()
