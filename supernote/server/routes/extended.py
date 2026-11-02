"""Module for server-specific extension routes.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    PageTranscriptVO,
    SearchResultVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebAiStatusVO,
    WebNoteCoverRequestDTO,
    WebNoteCoverVO,
    WebNoteMetadataRequestDTO,
    WebNoteMetadataVO,
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
from supernote.server.exceptions import SupernoteError
from supernote.server.services.conversion import ConversionService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.search import SearchService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

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
    processor_service: ProcessorService = request.app["processor_service"]

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
    processor_service: ProcessorService = request.app["processor_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
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
    # Purpose: Returns server AI processing configuration and capability health status.
    ocr_model: OcrModel | None = request.app.get("ocr_model")
    summary_model: SummaryModel | None = request.app.get("summary_model")
    embedding_model: EmbeddingModel | None = request.app.get("embedding_model")

    ocr_enabled = ocr_model is not None
    ocr_model_id = ocr_model.model_id if ocr_model is not None else None

    summary_enabled = summary_model is not None
    summary_model_id = summary_model.model_id if summary_model is not None else None

    vector_search_enabled = embedding_model is not None
    embedding_model_id = (
        embedding_model.model_id if embedding_model is not None else None
    )

    is_configured = any((ocr_enabled, summary_enabled, vector_search_enabled))
    primary_model = ocr_model_id or summary_model_id or embedding_model_id

    return web.json_response(
        WebAiStatusVO(
            has_api_key=is_configured,
            ocr_enabled=ocr_enabled,
            ocr_model=ocr_model_id,
            summary_enabled=summary_enabled,
            summary_model=summary_model_id,
            vector_search_enabled=vector_search_enabled,
            embedding_model=embedding_model_id,
            model=primary_model,
        ).to_dict()
    )


@routes.post("/api/extended/file/note/cover")
async def handle_extended_note_cover(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/note/cover
    # Purpose: Convert/fetch only the first page (page 0) PNG for lightweight explorer thumbnails.
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebNoteCoverRequestDTO.from_dict(data)
    except (json.JSONDecodeError, MissingField, InvalidFieldValue, ValueError) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    config: ServerConfig = request.app["config"]
    if not (config.web_enabled and config.web_notebook_preview):
        return web.json_response(WebNoteCoverVO(url=None).to_dict())

    conversion_service: ConversionService = request.app["conversion_service"]
    url_signer: UrlSigner = request.app["url_signer"]

    try:
        page_numbers = await conversion_service.convert_note_to_png(
            user_email, req_dto.file_id, page_indices={0}
        )
        if not page_numbers:
            return web.json_response(WebNoteCoverVO(url=None).to_dict())

        page_no = page_numbers[0]
        path_to_sign = f"/api/oss/png/{req_dto.file_id}/{page_no}"
        signed_path = await url_signer.sign(
            path_to_sign, user=user_email, single_use=False
        )
        download_url = f"{get_request_base_url(request)}{signed_path}"
        return web.json_response(WebNoteCoverVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error fetching note cover preview")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/file/note/metadata")
async def handle_extended_note_metadata(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/note/metadata
    # Purpose: Return structured notebook and per-page metadata (ink, drawables, style, outline, keywords, links).
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebNoteMetadataRequestDTO.from_dict(data)
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app["user_service"]
    processor_service: ProcessorService = request.app["processor_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
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
