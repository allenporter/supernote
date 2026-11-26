"""HTTP platform routes for note processing status, system tasks, and admin queue controls.

Mounts onto the main `aiohttp` application via `async_setup_http`:
- User endpoints: `GET /api/extended/system/tasks`, `POST /api/extended/system/tasks/retry`,
  `POST /api/extended/file/processing/status`
- Admin endpoints (`@require_admin`): `POST /api/admin/queue/stop`,
  `POST /api/admin/queue/start`, `GET /api/admin/queue/status`,
  `POST /api/admin/reprocess`, `GET /api/admin/tasks`
"""

from __future__ import annotations

import logging

from aiohttp import web

from supernote.models.base import (
    BaseResponse,
    ProcessingStatus,
    create_error_response,
)
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    RetrySystemTasksDTO,
    RetrySystemTasksVO,
    SystemTaskListVO,
    SystemTaskVO,
)
from supernote.models.system import QueueStatusVO
from supernote.server.components.http import (
    HttpRegistrar,
    parse_json_dto,
    parse_json_object,
)
from supernote.server.core import ServerCore
from supernote.server.exceptions import InvalidInputError, SupernoteError
from supernote.server.keys import (
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.routes.decorators import require_admin
from supernote.server.services.user import UserService

from . import PROCESSOR_SERVICE_KEY
from .service import ProcessorService

__all__ = [
    "async_setup_http",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/api/extended/system/tasks")
async def handle_list_system_tasks(request: web.Request) -> web.Response:
    """List recent system processing tasks and live queue status for the authenticated user."""
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response({"error": "User not found"}, status=404)

    try:
        task_vos, in_flight_ids = await processor_service.list_user_system_task_vos(
            user_id=user_id
        )
    except Exception as err:
        logger.exception("Error listing system tasks")
        return SupernoteError.uncaught(err).to_response()

    return web.json_response(
        SystemTaskListVO(
            tasks=task_vos,
            paused=not processor_service.is_processing_enabled(),
            queue_size=len(in_flight_ids),
            processing_file_ids=in_flight_ids,
        ).to_dict()
    )


@routes.post("/api/extended/system/tasks/retry")
async def handle_retry_system_tasks(request: web.Request) -> web.Response:
    """Clear failed task checkpoints for the authenticated user (or a specific file) and re-enqueue."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, RetrySystemTasksDTO, allow_empty=True)
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response({"error": "User not found"}, status=404)

    try:
        retried_ids = await processor_service.retry_failed_tasks(
            user_id=user_id,
            file_id=req_dto.file_id,
        )
        return web.json_response(
            RetrySystemTasksVO(retried_file_ids=retried_ids).to_dict()
        )
    except Exception as err:
        logger.exception("Error retrying failed system tasks")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/file/processing/status")
async def handle_file_processing_status(request: web.Request) -> web.Response:
    """Return aggregated processing status for a list of files."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, FileProcessingStatusDTO)
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response({"error": "User not found"}, status=404)

    try:
        statuses = await processor_service.get_file_processing_statuses(
            user_id=user_id,
            file_ids=req_dto.file_ids,
        )
        status_map = {str(fid): status for fid, status in statuses.items()}
        return web.json_response(
            FileProcessingStatusVO(status_map=status_map).to_dict()
        )
    except Exception as err:
        logger.exception("Error fetching processing status")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/admin/queue/stop")
@require_admin
async def handle_stop_queue(request: web.Request) -> web.Response:
    """Stop/pause the queue processing."""
    processor_service = request.app[PROCESSOR_SERVICE_KEY]
    await processor_service.pause()
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/admin/queue/start")
@require_admin
async def handle_start_queue(request: web.Request) -> web.Response:
    """Start/resume the queue processing."""
    processor_service = request.app[PROCESSOR_SERVICE_KEY]
    await processor_service.resume()
    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/admin/queue/status")
@require_admin
async def handle_queue_status(request: web.Request) -> web.Response:
    """Get the queue status."""
    processor_service = request.app[PROCESSOR_SERVICE_KEY]

    status = QueueStatusVO(
        paused=not processor_service.is_processing_enabled(),
        queue_size=processor_service.queue.qsize(),
        processing_files=list({fid for _, fid in processor_service.processing_files}),
    )
    return web.json_response(status.to_dict())


@routes.post("/api/admin/reprocess")
@require_admin
async def handle_reprocess(request: web.Request) -> web.Response:
    """Clear and trigger reprocessing of note tasks (Admin only)."""
    try:
        req_data = await parse_json_object(request)
    except InvalidInputError as err:
        return err.to_response()
    task_type = req_data.get("task_type", "summary")
    file_id = req_data.get("file_id")
    cascade = req_data.get("cascade", False)

    if not isinstance(task_type, str):
        return web.json_response(
            create_error_response("Invalid task_type").to_dict(),
            status=400,
        )
    if not isinstance(cascade, bool):
        return web.json_response(
            create_error_response("Invalid cascade: must be boolean").to_dict(),
            status=400,
        )

    processor_service = request.app[PROCESSOR_SERVICE_KEY]
    try:
        await processor_service.reprocess_tasks(
            task_type,
            file_id=file_id,
            cascade=cascade,
        )
    except ValueError as e:
        return web.json_response(
            create_error_response(str(e)).to_dict(),
            status=400,
        )

    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/admin/tasks")
@require_admin
async def handle_admin_list_tasks(request: web.Request) -> web.Response:
    """List system processing tasks with optional filters (Admin only)."""
    status_param = request.query.get("status")
    file_id_str = request.query.get("file_id")
    task_type_param = request.query.get("task_type")
    limit_str = request.query.get("limit")

    try:
        file_id = int(file_id_str) if file_id_str is not None else None
        limit = int(limit_str) if limit_str is not None else 100
    except ValueError:
        return web.json_response(
            create_error_response("Invalid file_id or limit").to_dict(),
            status=400,
        )

    status_filter: str | None = None
    if status_param:
        try:
            status_filter = ProcessingStatus(status_param.upper()).value
        except ValueError:
            return web.json_response(
                create_error_response(f"Invalid status: {status_param}").to_dict(),
                status=400,
            )

    processor_service = request.app[PROCESSOR_SERVICE_KEY]
    task_type_filter: str | None = None
    if task_type_param:
        try:
            task_type_filter = processor_service.resolve_task_type(task_type_param)
        except ValueError:
            return web.json_response(
                create_error_response(
                    f"Invalid task_type: {task_type_param}"
                ).to_dict(),
                status=400,
            )

    tasks = await processor_service.list_system_tasks(
        limit=limit,
        status=status_filter,
        file_id=file_id,
        task_type=task_type_filter,
    )
    task_vos = [
        SystemTaskVO(
            id=t.id,
            file_id=t.file_id,
            task_type=t.task_type,
            key=t.key,
            status=ProcessingStatus(t.status),
            retry_count=t.retry_count,
            last_error=t.last_error,
            update_time=t.update_time,
        )
        for t in tasks
    ]
    return web.json_response(SystemTaskListVO(tasks=task_vos).to_dict())


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register processor HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
