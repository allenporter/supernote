import logging
from typing import Any

from aiohttp import web

from supernote.models.base import BaseResponse, BooleanEnum, create_error_response
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
from supernote.server.services.schedule import ScheduleService

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.post("/api/schedule/groups")
async def create_group(request: web.Request) -> web.Response:
    user = request["user"]
    try:
        data = await request.json()
        dto = AddScheduleTaskGroupDTO.from_dict(data)
    except Exception as e:
        return web.json_response(
            create_error_response(f"Invalid request: {e}").to_dict(), status=400
        )

    if not dto.title:
        return web.json_response(
            create_error_response("Title required").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    try:
        group = await schedule_service.create_group(user_id, dto.title)
        return web.json_response(
            AddScheduleTaskGroupVO(
                success=True, task_list_id=str(group.task_list_id)
            ).to_dict()
        )
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)


@routes.get("/api/schedule/groups")
async def list_groups(request: web.Request) -> web.Response:
    user = request["user"]
    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    groups = await schedule_service.list_groups(user_id)

    # Map to ScheduleTaskGroupItem
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


@routes.delete("/api/schedule/groups/{id}")
async def delete_group(request: web.Request) -> web.Response:
    user = request["user"]
    group_id = int(request.match_info["id"])
    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    success = await schedule_service.delete_group(user_id, group_id)
    if not success:
        return web.json_response(
            create_error_response("Not found").to_dict(), status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())


@routes.post("/api/schedule/tasks")
async def create_task(request: web.Request) -> web.Response:
    user = request["user"]
    try:
        data = await request.json()
        dto = AddScheduleTaskDTO.from_dict(data)
    except Exception as e:
        return web.json_response(
            create_error_response(f"Invalid request: {e}").to_dict(), status=400
        )

    if not dto.task_list_id or not dto.title:
        return web.json_response(
            create_error_response("Missing required fields").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    try:
        task = await schedule_service.create_task(
            user_id=user_id,
            group_id=int(dto.task_list_id),
            title=dto.title,
            detail=dto.detail or "",
            status=dto.status or "needsAction",
            importance=dto.importance,
            due_time=dto.due_time,
            recurrence=dto.recurrence,
            is_reminder_on=(dto.is_reminder_on == BooleanEnum.YES),
        )
        return web.json_response(
            AddScheduleTaskVO(success=True, task_id=str(task.task_id)).to_dict()
        )
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)


@routes.get("/api/schedule/tasks")
async def list_tasks(request: web.Request) -> web.Response:
    user = request["user"]
    group_id_str = request.query.get("taskListId")
    group_id = int(group_id_str) if group_id_str else None

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
            is_reminder_on=(BooleanEnum.YES if t.is_reminder_on else BooleanEnum.NO),
            last_modified=t.update_time,
        )
        for t in tasks_dos
    ]

    return web.json_response(
        ScheduleTaskAllVO(success=True, schedule_task=tasks_vos).to_dict()
    )


@routes.put("/api/schedule/tasks/{id}")
async def update_task(request: web.Request) -> web.Response:
    user = request["user"]
    task_id = int(request.match_info["id"])
    try:
        data = await request.json()
        dto = UpdateScheduleTaskDTO.from_dict(data)
    except Exception as e:
        return web.json_response(
            create_error_response(f"Invalid request: {e}").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    updates: dict[str, Any] = {}
    if dto.title is not None:
        updates["title"] = dto.title
    if dto.detail is not None:
        updates["detail"] = dto.detail
    if dto.status is not None:
        updates["status"] = dto.status
    if dto.importance is not None:
        updates["importance"] = dto.importance
    if dto.due_time is not None:
        updates["due_time"] = dto.due_time
    if dto.recurrence is not None:
        updates["recurrence"] = dto.recurrence
    if dto.is_reminder_on is not None:
        updates["is_reminder_on"] = dto.is_reminder_on == BooleanEnum.YES
    if dto.task_list_id is not None:
        updates["task_list_id"] = int(dto.task_list_id)

    updated_task = await schedule_service.update_task(user_id, task_id, **updates)
    if not updated_task:
        return web.json_response(
            create_error_response("Not found").to_dict(), status=404
        )

    return web.json_response(
        UpdateScheduleTaskVO(success=True, task_id=str(updated_task.task_id)).to_dict()
    )


@routes.delete("/api/schedule/tasks/{id}")
async def delete_task(request: web.Request) -> web.Response:
    user = request["user"]
    task_id = int(request.match_info["id"])
    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    success = await schedule_service.delete_task(user_id, task_id)
    if not success:
        return web.json_response(
            create_error_response("Not found").to_dict(), status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())
