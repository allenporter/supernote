"""Open Private Cloud extension routes (`/api/extended/*`) for summaries, tasks, API keys, and AI status.

Exposes non-device HTTP endpoints consumed by the Web UI and `supernote.client.extended.ExtendedClient`:
- `POST /api/extended/summary/list`: Notebook summaries and transcripts for a given `file_id`.
- `POST /api/extended/file/status` and `GET /api/extended/system/tasks`: Per-file and global pipeline task statuses (`SystemTaskDO`) and active AI capability flags.

See `supernote.guides.mcp` and `supernote.guides.note_processing_design`.
"""

import json
import logging
import time

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.base import BaseResponse, ProcessingStatus
from supernote.models.extended import (
    ApiKeyListResponseVO,
    CreateApiKeyDTO,
    CreateApiKeyResponseVO,
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    OAuthGrantListResponseVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebNoteCoverRequestDTO,
    WebNoteCoverVO,
    WebNoteMetadataRequestDTO,
    WebNoteMetadataVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
)
from supernote.server.config import ServerConfig
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    CONFIG_KEY,
    CONVERSION_SERVICE_KEY,
    PROCESSOR_SERVICE_KEY,
    REQUEST_USER_KEY,
    SUMMARY_SERVICE_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.conversion import ConversionService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

from .decorators import interactive_session_only

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.post("/api/extended/file/summary/list")
async def handle_extended_file_summary_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/list
    # Purpose: Extended API to list summaries for a file.
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        req_dto = WebSummaryListRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

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
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

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
    user_email = request[REQUEST_USER_KEY]
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

    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

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


@routes.post("/api/extended/file/note/cover")
async def handle_extended_note_cover(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/note/cover
    # Purpose: Convert/fetch only the first page (page 0) PNG for lightweight explorer thumbnails.
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
        req_dto = WebNoteCoverRequestDTO.from_dict(data)
    except (json.JSONDecodeError, MissingField, InvalidFieldValue, ValueError) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    config: ServerConfig = request.app[CONFIG_KEY]
    if not (config.web_enabled and config.web_notebook_preview):
        return web.json_response(WebNoteCoverVO(url=None).to_dict())

    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

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
    # Purpose: Return structured notebook and per-page metadata.
    user_email = request[REQUEST_USER_KEY]
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

    user_service: UserService = request.app[USER_SERVICE_KEY]
    processor_service: ProcessorService = request.app[PROCESSOR_SERVICE_KEY]

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


@routes.get("/api/extended/keys")
@interactive_session_only
async def handle_list_api_keys(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/keys
    # Purpose: List active static Bearer API keys for the authenticated user.
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    keys = await user_service.list_api_keys(user_id)
    return web.json_response(ApiKeyListResponseVO(keys=keys).to_dict())


@routes.post("/api/extended/keys")
@interactive_session_only
async def handle_create_api_key(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/keys
    # Purpose: Generate and return a new static Bearer API key.
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = CreateApiKeyDTO.from_dict(await request.json())
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    expires_at: int | None = None
    if req_dto.expires_in_days is not None:
        if req_dto.expires_in_days <= 0 or req_dto.expires_in_days > 3650:
            return web.json_response(
                {"error": "expiresInDays must be between 1 and 3650"}, status=400
            )
        expires_at = int(time.time()) + req_dto.expires_in_days * 86400

    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    try:
        raw_token, vo = await user_service.create_api_key(
            user_id, req_dto.name, expires_at=expires_at
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)

    return web.json_response(
        CreateApiKeyResponseVO(
            id=vo.id,
            name=vo.name,
            key=raw_token,
            created_at=vo.created_at,
            expires_at=vo.expires_at,
        ).to_dict()
    )


@routes.delete("/api/extended/keys/{key_id}")
@interactive_session_only
async def handle_delete_api_key(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/extended/keys/{key_id}
    # Purpose: Revoke an existing static Bearer API key.
    user_email = request[REQUEST_USER_KEY]
    key_id = request.match_info["key_id"]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)

    revoked = await user_service.revoke_api_key(user_id, key_id)
    if not revoked:
        return web.json_response(
            {"error": "API key not found or already revoked"}, status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())


@routes.get("/api/extended/oauth/grants")
@interactive_session_only
async def handle_list_oauth_grants(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/oauth/grants
    # Purpose: List MCP OAuth clients the authenticated user has authorized.
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    grants = await user_service.list_oauth_grants(user_id)
    return web.json_response(OAuthGrantListResponseVO(grants=grants).to_dict())


@routes.delete("/api/extended/oauth/grants/{grant_id}")
@interactive_session_only
async def handle_revoke_oauth_grant(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/extended/oauth/grants/{grant_id}
    # Purpose: Disconnect an MCP OAuth client, ending its access and refresh tokens.
    user_email = request[REQUEST_USER_KEY]
    grant_id = request.match_info["grant_id"]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)

    revoked = await user_service.revoke_oauth_grant(user_id, grant_id)
    if not revoked:
        return web.json_response(
            {"error": "OAuth grant not found or already revoked"}, status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())
