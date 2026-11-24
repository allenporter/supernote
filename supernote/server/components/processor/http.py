"""HTTP platform routes for note processing status, system tasks, and notebook metadata.

Mounts `GET /api/extended/system/tasks`, `POST /api/extended/file/processing/status`,
and `POST /api/extended/file/note/metadata` onto the main `aiohttp` application via
`async_setup_http`.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    RetrySystemTasksDTO,
    RetrySystemTasksVO,
    SystemTaskListVO,
    WebNoteMetadataRequestDTO,
    WebNoteMetadataVO,
)
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    PROCESSOR_SERVICE_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.user import UserService

from .service import ProcessorService

__all__ = [
    "async_setup_http",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

_PARSE_ERRORS = (
    json.JSONDecodeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    MissingField,
    InvalidFieldValue,
)


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
        data = await request.json() if request.can_read_body else {}
        req_dto = RetrySystemTasksDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

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
        data = await request.json()
        req_dto = FileProcessingStatusDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

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


@routes.post("/api/extended/file/note/metadata")
async def handle_extended_note_metadata(request: web.Request) -> web.Response:
    """Return structured notebook and per-page metadata for an active `.note` file."""
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
        req_dto = WebNoteMetadataRequestDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response({"error": "User not found"}, status=404)

    try:
        metadata_vo: (
            WebNoteMetadataVO | None
        ) = await processor_service.get_note_metadata(
            user_id=user_id,
            file_id=req_dto.file_id,
        )
        if metadata_vo is None:
            return web.json_response(
                {"error": f"No metadata found for notebook {req_dto.file_id}"},
                status=404,
            )
        return web.json_response(metadata_vo.to_dict())
    except Exception as err:
        logger.exception("Error fetching notebook metadata")
        return SupernoteError.uncaught(err).to_response()


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register processor HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
