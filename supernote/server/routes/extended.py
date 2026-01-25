"""Module for server-specific extension routes.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

import logging

from aiohttp import web
from sqlalchemy import select

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
)
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.exceptions import SupernoteError
from supernote.server.services.summary import SummaryService

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.post("/api/extended/file/summary/list")
async def handle_extended_file_summary_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/list
    # Purpose: Extended API to list summaries for a file.
    user_email = request["user"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        req_dto = WebSummaryListRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    summary_service: SummaryService = request.app["summary_service"]

    try:
        summaries = await summary_service.list_summaries_for_file_internal(
            user_email, req_dto.file_id
        )
        return web.json_response(
            WebSummaryListVO(
                summary_do_list=summaries, total_records=len(summaries)
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error fetching summaries")
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/extended/system/tasks")
async def handle_list_system_tasks(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/tasks
    # Purpose: Extended API to list system tasks for the control panel.

    processor_service = request.app["processor_service"]

    try:
        tasks = await processor_service.list_system_tasks()
    except Exception as err:
        logger.exception("Error listing system tasks")
        return SupernoteError.uncaught(err).to_response()

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


@routes.post("/api/extended/file/processing/status")
async def handle_file_processing_status(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/processing/status
    # Purpose: Get aggregated processing status for a list of files.

    try:
        data = await request.json()
        req_dto = FileProcessingStatusDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    session_manager = request.app["session_manager"]

    try:
        status_map = {}
        async with session_manager.session() as session:
            for file_id in req_dto.file_ids:
                # Aggregate tasks for this file
                stmt = select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
                result = await session.execute(stmt)
                tasks = result.scalars().all()

                if not tasks:
                    status_map[str(file_id)] = ProcessingStatus.NONE
                    continue

                # Logic:
                # If any FAILED -> FAILED
                # If any PROCESSING -> PROCESSING
                # If all COMPLETED -> COMPLETED
                # Else -> PENDING

                if any(t.status == ProcessingStatus.FAILED for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.FAILED
                elif any(t.status == ProcessingStatus.PROCESSING for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.PROCESSING
                elif all(t.status == ProcessingStatus.COMPLETED for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.COMPLETED
                else:
                    status_map[str(file_id)] = ProcessingStatus.PENDING

        return web.json_response(
            FileProcessingStatusVO(status_map=status_map).to_dict()
        )
    except Exception as err:
        logger.exception("Error fetching processing status")
        return SupernoteError.uncaught(err).to_response()
