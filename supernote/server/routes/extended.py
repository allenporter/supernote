"""Knowledge Hub extension routes (`/api/extended/*`) for search, transcripts, and AI status.

Exposes non-device HTTP endpoints consumed by the Web UI and `supernote.client.extended.ExtendedClient`:
- `POST /api/extended/search`: Semantic vector search across notebook pages via `supernote.server.services.search.SearchService`.
- `POST /api/extended/transcript`: Full or page-range OCR transcript retrieval.
- `POST /api/extended/summary/list`: Notebook summaries and transcripts for a given `file_id`.
- `POST /api/extended/file/status` and `GET /api/extended/system/tasks`: Per-file and global pipeline task statuses (`SystemTaskDO`) and active AI capability flags.

See `supernote.guides.mcp` and `supernote.guides.note_processing_design`.
"""

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField
from sqlalchemy import select

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    PageTranscriptVO,
    SearchResultVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.server.ai.models.embedding import EmbeddingModel
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.exceptions import SupernoteError
from supernote.server.services.search import SearchService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService

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
    user_email = request["user"]
    user_service: UserService = request.app["user_service"]
    processor_service = request.app["processor_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        tasks = await processor_service.list_system_tasks(user_id=user_id)
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
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = FileProcessingStatusDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    session_manager = request.app["session_manager"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        status_map = {}
        async with session_manager.session() as session:
            for file_id in req_dto.file_ids:
                # Aggregate tasks for this file belonging to the requesting user
                stmt = (
                    select(SystemTaskDO)
                    .join(UserFileDO, SystemTaskDO.file_id == UserFileDO.id)
                    .where(
                        SystemTaskDO.file_id == file_id,
                        UserFileDO.user_id == user_id,
                    )
                )
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


@routes.post("/api/extended/search")
async def handle_extended_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/search
    # Purpose: Semantic search across notebook content.
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebSearchRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    search_service: SearchService = request.app["search_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        results = await search_service.search_chunks(
            user_id=user_id,
            query=req_dto.query,
            top_n=req_dto.top_n,
            name_filter=req_dto.name_filter,
            date_after=req_dto.date_after,
            date_before=req_dto.date_before,
        )

        vo_results = [
            SearchResultVO(
                file_id=r.file_id,
                file_name=r.file_name,
                page_index=r.page_index,
                page_id=r.page_id,
                score=float(r.score),
                text_preview=r.text_preview,
                date=r.date,
            )
            for r in results
        ]

        return web.json_response(WebSearchResponseVO(results=vo_results).to_dict())
    except Exception as err:
        logger.exception("Error performing semantic search")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/transcript")
async def handle_extended_transcript(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/transcript
    # Purpose: Retrieve structured per-page notebook transcript.
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebTranscriptRequestDTO.from_dict(data)
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ) as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    search_service: SearchService = request.app["search_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        page_transcripts = await search_service.get_page_transcripts(
            user_id=user_id,
            file_id=req_dto.file_id,
            start_index=req_dto.start_index,
            end_index=req_dto.end_index,
        )

        if not page_transcripts:
            return web.json_response(
                {"error": f"No transcript found for notebook {req_dto.file_id}"},
                status=404,
            )

        vo_pages = [
            PageTranscriptVO(
                page_index=p.page_index,
                page_id=p.page_id,
                text=p.text,
                date=p.date,
            )
            for p in page_transcripts
        ]

        return web.json_response(WebTranscriptResponseVO(pages=vo_pages).to_dict())
    except Exception as err:
        logger.exception("Error fetching notebook transcript")
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/extended/ai/status")
async def handle_extended_ai_status(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/ai/status
    # Purpose: Returns server AI processing configuration and API key health status.
    config: ServerConfig | None = request.app.get("config")
    ocr_model: OcrModel | None = request.app.get("ocr_model")
    summary_model: SummaryModel | None = request.app.get("summary_model")
    embedding_model: EmbeddingModel | None = request.app.get("embedding_model")
    is_configured = any((ocr_model, summary_model, embedding_model))
    ocr_enabled = ocr_model is not None
    vector_search_enabled = embedding_model is not None
    model = (
        ocr_model.model_id
        if ocr_model is not None
        else (
            config.ai.ocr.model
            if config is not None and config.ai.ocr is not None
            else (config.gemini_ocr_model if config is not None else None)
        )
    )

    return web.json_response(
        {
            "success": True,
            "hasApiKey": is_configured,
            "ocrEnabled": ocr_enabled,
            "vectorSearchEnabled": vector_search_enabled,
            "model": model,
        }
    )
