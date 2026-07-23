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
    UpdateScheduleTaskListDTO,
    UpdateScheduleTaskVO,
)
from supernote.server.services.schedule import (
    DEVICE_TASK_PASSTHROUGH_FIELDS,
    ScheduleService,
)

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


async def _all_groups_response(request: web.Request) -> web.Response:
    """Build the ScheduleTaskGroupVO listing every group for the request's user.

    Shared by the bespoke ``GET /api/schedule/groups`` (CLI) and the spec
    ``POST /api/file/schedule/group/all`` (device) handlers, which return the
    identical payload.
    """
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


@routes.get("/api/schedule/groups")
async def list_groups(request: web.Request) -> web.Response:
    return await _all_groups_response(request)


@routes.post("/api/file/schedule/group/all")
async def device_list_groups(request: web.Request) -> web.Response:
    """List all schedule groups for the device planner sync (spec route).

    The Supernote device syncs its planner via the community-spec
    ``POST /api/file/schedule/group/all`` endpoint, distinct from the bespoke
    ``GET /api/schedule/groups`` the CLI uses. Without this route the device's call
    404s, which the firmware surfaces as "private cloud sync failed". The request body
    is a ``ScheduleTaskGroupDTO`` (pagination); pagination is not yet applied — all
    groups are returned, mirroring ``list_groups``.
    """
    return await _all_groups_response(request)


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

    if not dto.title:
        return web.json_response(
            create_error_response("Missing required fields").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    try:
        task = await schedule_service.create_task(
            user_id=user_id,
            # Ungrouped when no taskListId is given, matching the device's task shape.
            group_id=int(dto.task_list_id) if dto.task_list_id else None,
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


def _device_task_upsert_kwargs(
    dto: AddScheduleTaskDTO | UpdateScheduleTaskDTO,
) -> dict[str, Any] | None:
    """Coerce one device task DTO into :meth:`ScheduleService.upsert_task` kwargs.

    The single-task ``POST /api/file/schedule/task`` and the batch
    ``PUT /api/file/schedule/task/list`` carry the identical task shape (a device string
    ``taskId`` plus the rich fields), so both funnel through here. Returns ``None`` for a
    malformed item (missing ``taskId``/``title``) so callers can 400 or skip it. The
    fields needing a wire->store transform are spelled out; the rest ride through
    verbatim via :data:`DEVICE_TASK_PASSTHROUGH_FIELDS`.
    """
    if not dto.task_id or not dto.title:
        return None

    return {
        "device_task_id": dto.task_id,
        "title": dto.title,
        "task_list_id": int(dto.task_list_id) if dto.task_list_id else None,
        "status": dto.status or "needsAction",
        "is_reminder_on": (dto.is_reminder_on == BooleanEnum.YES),
        "is_deleted": (dto.is_deleted == BooleanEnum.YES),
        **{name: getattr(dto, name) for name in DEVICE_TASK_PASSTHROUGH_FIELDS},
    }


@routes.post("/api/file/schedule/task")
async def device_upsert_task(request: web.Request) -> web.Response:
    """Create/update a task from the device planner sync (spec route).

    The Supernote device pushes planner changes as a ``POST /api/file/schedule/task``
    carrying its own opaque string ``taskId``. While unregistered this 404'd, so no
    device task could ever be stored ("private cloud sync failed"). This upserts on
    ``(user_id, taskId)`` via :meth:`ScheduleService.upsert_task`, tombstoning on
    ``isDeleted='Y'``, and echoes the device's own id back so it can reconcile the ack.
    Distinct from the bespoke CLI ``POST /api/schedule/tasks`` (insert-only,
    server-generated int id), which is left untouched. The device also batches edits via
    ``PUT /api/file/schedule/task/list`` (see :func:`device_update_task_list`).
    """
    user = request["user"]
    try:
        data = await request.json()
        dto = AddScheduleTaskDTO.from_dict(data)
    except Exception as e:
        return web.json_response(
            create_error_response(f"Invalid request: {e}").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    kwargs = _device_task_upsert_kwargs(dto)
    if kwargs is None:
        return web.json_response(
            create_error_response("Missing required fields").to_dict(), status=400
        )
    try:
        await schedule_service.upsert_task(user_id, **kwargs)
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)

    # Echo the device's own taskId, not the server surrogate.
    return web.json_response(
        AddScheduleTaskVO(success=True, task_id=kwargs["device_task_id"]).to_dict()
    )


@routes.put("/api/file/schedule/task/list")
async def device_update_task_list(request: web.Request) -> web.Response:
    """Batch-update tasks from the device planner sync (spec route).

    The device pushes edits/completions/reorders as a single
    ``PUT /api/file/schedule/task/list`` carrying an ``updateScheduleTaskList`` array,
    each item the same shape as a single push. While unregistered this 404'd, so device
    edits never reached the store. Each item upserts on ``(user_id, taskId)`` — the same
    seam as the single-task route. Structurally malformed items (missing ``taskId``) are
    skipped; the rest apply in one atomic transaction, so a validation failure rolls the
    whole batch back rather than leaving it half-written. Returns a bare success
    ``BaseResponse`` per the spec.
    """
    user = request["user"]
    try:
        data = await request.json()
        dto = UpdateScheduleTaskListDTO.from_dict(data)
    except Exception as e:
        return web.json_response(
            create_error_response(f"Invalid request: {e}").to_dict(), status=400
        )

    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    items = [
        kwargs
        for item in dto.update_schedule_task_list
        if (kwargs := _device_task_upsert_kwargs(item)) is not None
    ]
    try:
        await schedule_service.upsert_tasks(user_id, items)
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)

    return web.json_response(BaseResponse(success=True).to_dict())


async def _all_tasks_response(
    request: web.Request, group_id: int | None
) -> web.Response:
    """Build the ScheduleTaskAllVO listing the request user's tasks.

    Shared by the bespoke ``GET /api/schedule/tasks`` (CLI, optionally filtered to one
    group via ``taskListId``) and the spec ``POST /api/file/schedule/task/all`` (device,
    account-wide with ``group_id=None``), which return the identical payload.
    """
    user = request["user"]
    schedule_service: ScheduleService = request.app["schedule_service"]
    user_id = await request.app["user_service"].get_user_id(user)

    tasks_dos = await schedule_service.list_tasks(user_id, group_id)

    tasks_vos = [
        ScheduleTaskInfo(
            # Echo the device's own id for device rows; the surrogate PK for CLI rows.
            task_id=t.device_task_id
            if t.device_task_id is not None
            else str(t.task_id),
            # Ungrouped (device) tasks have no task_list_id; emit null, not "None".
            task_list_id=(str(t.task_list_id) if t.task_list_id is not None else None),
            title=t.title,
            status=t.status,
            is_reminder_on=(BooleanEnum.YES if t.is_reminder_on else BooleanEnum.NO),
            is_deleted=(BooleanEnum.YES if t.is_deleted else BooleanEnum.NO),
            # Device's own lastModified if it set one, else server bookkeeping time.
            last_modified=(
                t.last_modified if t.last_modified is not None else t.update_time
            ),
            # The verbatim device fields ride straight through (last_modified above has
            # its own read fallback, so exclude it from the passthrough).
            **{
                name: getattr(t, name)
                for name in DEVICE_TASK_PASSTHROUGH_FIELDS
                if name != "last_modified"
            },
        )
        for t in tasks_dos
    ]

    return web.json_response(
        ScheduleTaskAllVO(success=True, schedule_task=tasks_vos).to_dict()
    )


@routes.get("/api/schedule/tasks")
async def list_tasks(request: web.Request) -> web.Response:
    group_id_str = request.query.get("taskListId")
    group_id = int(group_id_str) if group_id_str else None
    return await _all_tasks_response(request, group_id)


@routes.post("/api/file/schedule/task/all")
async def device_list_tasks(request: web.Request) -> web.Response:
    """List all schedule tasks for the device planner sync (spec route).

    The device calls ``POST /api/file/schedule/task/all`` immediately after
    ``group/all`` on every sync; while unregistered it 404s, which keeps the "private
    cloud sync failed" banner even once ``group/all`` returns 200. This is account-wide
    (``group_id=None`` → tasks across all of the user's groups), unlike the bespoke
    ``GET /api/schedule/tasks`` which can filter to one group. The request body is a
    ``ScheduleTaskDTO`` (pagination / sync tokens); pagination is not yet applied.
    """
    return await _all_tasks_response(request, None)


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
