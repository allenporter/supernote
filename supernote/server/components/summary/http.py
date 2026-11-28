"""Summary group, summary item, summary tag, and extended summary HTTP routes.

Implements the Supernote summary synchronization protocol (`supernote.models.summary`)
for both AI-generated syntheses and device-authored handwritten summaries, including
tag CRUD (`/api/file/*/summary/tag`), summary group CRUD (`/api/file/*/summary/group`),
summary item CRUD (`/api/file/add/summary`, `/api/file/update/summary`,
`/api/file/delete/summary`, `/api/file/query/summary*`), signed binary upload/download
URL generation for handwriting blobs, the extended Web UI listing endpoint
(`POST /api/extended/file/summary/list`), and extended handwriting renders
(`POST /api/extended/file/summary/to/pdf|png`, served from `GET /api/oss/summary/*`).
Delegates persistence and event emission to
`supernote.server.components.summary.service.SummaryService`.
See `supernote.guides.summary_api`.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus

from aiohttp import web
from mashumaro import field_options
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse, create_error_response
from supernote.models.extended import (
    DigestListRequestDTO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
)
from supernote.models.file_device import PdfVO, PngPageVO, PngVO
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    AddSummaryGroupVO,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    AddSummaryVO,
    DeleteSummaryDTO,
    DeleteSummaryGroupDTO,
    DeleteSummaryTagDTO,
    DownloadSummaryDTO,
    DownloadSummaryVO,
    QuerySummaryByIdVO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    QuerySummaryGroupVO,
    QuerySummaryMD5HashVO,
    QuerySummaryTagVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
    UpdateSummaryTagDTO,
    UploadSummaryApplyDTO,
    UploadSummaryApplyVO,
)
from supernote.server.components.conversion import (
    CONVERSION_SERVICE_KEY,
    ConversionService,
)
from supernote.server.components.http import (
    HttpRegistrar,
    parse_json_dto,
    parse_query_dto,
)
from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    TranscriptService,
)
from supernote.server.constants import CACHE_BUCKET
from supernote.server.core import ServerCore
from supernote.server.exceptions import (
    InvalidInputError,
    SummaryNotFound,
    SupernoteError,
)
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    REQUEST_USER_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.metrics import OSSTransferKind
from supernote.server.routes.decorators import public_route
from supernote.server.routes.oss import stream_blob_response
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService
from supernote.server.utils.paths import generate_inner_name
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

from .markdown_export import format_digests_markdown
from .service import (
    DEFAULT_SUMMARY_PAGE_SIZE,
    SUMMARY_SERVICE_KEY,
    SummaryService,
)

__all__ = [
    "async_setup_http",
    "routes",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@dataclass(frozen=True, kw_only=True)
class _PaginationMetadata:
    """Resolved pagination envelope fields for summary query responses."""

    total_records: int
    total_pages: int
    current_page: int
    page_size: int


async def _resolve_pagination_metadata(
    items_count: int,
    page: int | None,
    size: int | None,
    count_fn: Callable[[], Awaitable[int]],
) -> _PaginationMetadata:
    """Resolve pagination envelope fields across paginated and unpaginated summary queries.

    Supernote clients query summary endpoints in two distinct modes:
    1. Paginated queries (where ``size > 0``), which require total record and page
       counts so the client can iterate through pages. When the first page already
       contains fewer items than ``size``, ``total_records`` is known to equal
       ``items_count`` and we skip the extra database ``COUNT(*)`` roundtrip.
    2. Unpaginated manifest or batch ID queries (where devices send ``page=0, size=0``
       or omit ``size`` on ``/api/file/query/summary/hash`` and ID-filtered queries),
       where all matching records are returned in a single page and no separate count
       query is needed.
    """
    current_page = max(1, page or 1)
    if size is None or size <= 0:
        return _PaginationMetadata(
            total_records=items_count,
            total_pages=1,
            current_page=current_page,
            page_size=items_count,
        )
    if current_page == 1 and items_count < size:
        total_records = items_count
    else:
        total_records = await count_fn()
    total_pages = max(1, (total_records + size - 1) // size)
    return _PaginationMetadata(
        total_records=total_records,
        total_pages=total_pages,
        current_page=current_page,
        page_size=size,
    )


@routes.post("/api/file/add/summary/tag")
async def handle_add_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary/tag
    # Purpose: Add a new summary tag.
    # Response: AddSummaryTagVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, AddSummaryTagDTO)
        tag = await summary_service.add_tag(user_email, req_data.name)
        return web.json_response(AddSummaryTagVO(id=tag.id).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/update/summary/tag")
@routes.post("/api/file/update/summary/tag")
async def handle_update_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: PUT /api/file/update/summary/tag
    # Purpose: Update an existing summary tag.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, UpdateSummaryTagDTO)
        await summary_service.update_tag(user_email, req_data.id, req_data.name)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.delete("/api/file/delete/summary/tag")
@routes.post("/api/file/delete/summary/tag")
async def handle_delete_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/file/delete/summary/tag
    # Purpose: Delete a summary tag.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, DeleteSummaryTagDTO)
        await summary_service.delete_tag(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/file/query/summary/tag")
@routes.post("/api/file/query/summary/tag")
async def handle_query_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: GET /api/file/query/summary/tag
    # Purpose: Query summary tags.
    # Response: QuerySummaryTagVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        tags = await summary_service.list_tags(user_email)
        return web.json_response(QuerySummaryTagVO(summary_tag_do_list=tags).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/add/summary")
async def handle_add_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary
    # Purpose: Add a new summary.
    # Response: AddSummaryVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, AddSummaryDTO)
        summary = await summary_service.add_summary(user_email, req_data)
        return web.json_response(AddSummaryVO(id=summary.id).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/update/summary")
@routes.post("/api/file/update/summary")
async def handle_update_summary(request: web.Request) -> web.Response:
    # Endpoint: PUT /api/file/update/summary
    # Purpose: Update an existing summary.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, UpdateSummaryDTO)
        await summary_service.update_summary(user_email, req_data)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.delete("/api/file/delete/summary")
@routes.post("/api/file/delete/summary")
async def handle_delete_summary(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/file/delete/summary
    # Purpose: Delete a summary.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, DeleteSummaryDTO)
        await summary_service.delete_summary(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary")
async def handle_query_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary
    # Purpose: Query summaries.
    # Response: QuerySummaryVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, QuerySummaryDTO)
        size = (
            req_data.size
            if (req_data.size is not None or req_data.ids is not None)
            else DEFAULT_SUMMARY_PAGE_SIZE
        )
        summaries = await summary_service.list_summaries(
            user_email,
            parent_uuid=req_data.parent_unique_identifier,
            ids=req_data.ids,
            page=req_data.page,
            size=size,
        )
        pagination = await _resolve_pagination_metadata(
            len(summaries),
            req_data.page,
            size,
            lambda: summary_service.count_summaries(
                user_email,
                parent_uuid=req_data.parent_unique_identifier,
                ids=req_data.ids,
            ),
        )
        return web.json_response(
            QuerySummaryVO(
                summary_do_list=summaries,
                total_records=pagination.total_records,
                total_pages=pagination.total_pages,
                current_page=pagination.current_page,
                page_size=pagination.page_size,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/add/summary/group")
async def handle_add_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary/group
    # Purpose: Add a new summary group.
    # Response: AddSummaryGroupVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, AddSummaryGroupDTO)
        group = await summary_service.add_group(user_email, req_data)
        return web.json_response(AddSummaryGroupVO(id=group.id).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.put("/api/file/update/summary/group")
@routes.post("/api/file/update/summary/group")
async def handle_update_summary_group(request: web.Request) -> web.Response:
    # Endpoint: PUT /api/file/update/summary/group
    # Purpose: Update an existing summary group.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, UpdateSummaryGroupDTO)
        await summary_service.update_group(user_email, req_data)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.delete("/api/file/delete/summary/group")
@routes.post("/api/file/delete/summary/group")
async def handle_delete_summary_group(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/file/delete/summary/group
    # Purpose: Delete a summary group.
    # Response: BaseResponse
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, DeleteSummaryGroupDTO)
        await summary_service.delete_group(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/group")
async def handle_query_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/group
    # Purpose: Query summary groups.
    # Response: QuerySummaryGroupVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, QuerySummaryGroupDTO)
        size = DEFAULT_SUMMARY_PAGE_SIZE if req_data.size is None else req_data.size
        groups = await summary_service.list_groups(
            user_email, QuerySummaryGroupDTO(page=req_data.page, size=size)
        )
        pagination = await _resolve_pagination_metadata(
            len(groups),
            req_data.page,
            size,
            lambda: summary_service.count_groups(user_email),
        )
        return web.json_response(
            QuerySummaryGroupVO(
                summary_do_list=groups,
                total_records=pagination.total_records,
                total_pages=pagination.total_pages,
                current_page=pagination.current_page,
                page_size=pagination.page_size,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/upload/apply/summary")
async def handle_upload_apply_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/apply/summary
    # Purpose: Apply for upload (signed URL).
    # Response: UploadSummaryApplyVO
    user_email = request[REQUEST_USER_KEY]

    try:
        req_data = await parse_json_dto(request, UploadSummaryApplyDTO)
        url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

        # Generate inner name
        inner_name = generate_inner_name(req_data.file_name, req_data.equipment_no)
        encoded_name = urllib.parse.quote(inner_name)

        # Sign URLs
        base_url = get_request_base_url(request)
        full_path = f"/api/oss/upload?path={encoded_name}"
        full_url_path = await url_signer.sign(full_path, user=user_email)
        full_url = f"{base_url}{full_url_path}"

        part_path = f"/api/oss/upload/part?path={encoded_name}"
        part_url_path = await url_signer.sign(part_path, user=user_email)
        part_url = f"{base_url}{part_url_path}"

        return web.json_response(
            UploadSummaryApplyVO(
                full_upload_url=full_url,
                part_upload_url=part_url,
                inner_name=inner_name,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/download/summary")
async def handle_download_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/download/summary
    # Purpose: Get signed download URL for binary content.
    # Response: DownloadSummaryVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, DownloadSummaryDTO)
        summary = await summary_service.get_summary(user_email, req_data.id)
        if not summary.handwrite_inner_name:
            raise SummaryNotFound("Handwriting data not found")

        url_signer: UrlSigner = request.app[URL_SIGNER_KEY]
        encoded_name = urllib.parse.quote(summary.handwrite_inner_name)
        download_path = f"/api/oss/download?path={encoded_name}"
        signed_path = await url_signer.sign(
            download_path, user=user_email, single_use=False
        )
        base_url = get_request_base_url(request)
        download_url = f"{base_url}{signed_path}"

        return web.json_response(DownloadSummaryVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/hash")
async def handle_query_summary_hash(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/hash
    # Purpose: Query summary lightweight info (hash/integrity).
    # Response: QuerySummaryMD5HashVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, QuerySummaryDTO)
        infos = await summary_service.list_summary_infos(user_email, req_data)
        pagination = await _resolve_pagination_metadata(
            len(infos),
            req_data.page,
            req_data.size,
            lambda: summary_service.count_summaries(
                user_email,
                parent_uuid=req_data.parent_unique_identifier,
                ids=req_data.ids,
            ),
        )
        return web.json_response(
            QuerySummaryMD5HashVO(
                summary_info_vo_list=infos,
                total_records=pagination.total_records,
                total_pages=pagination.total_pages,
                current_page=pagination.current_page,
                page_size=pagination.page_size,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/id")
async def handle_query_summary_id(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/id
    # Purpose: Query full summaries by ID.
    # Response: QuerySummaryByIdVO
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]

    try:
        req_data = await parse_json_dto(request, QuerySummaryDTO)
        summaries = await summary_service.list_summaries_by_id(user_email, req_data)
        return web.json_response(
            QuerySummaryByIdVO(summary_do_list=summaries).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/extended/digests")
async def handle_list_digests(request: web.Request) -> web.Response:
    """List self-contained Digests with inline handwriting OCR transcripts."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = parse_query_dto(request, DigestListRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

    user_service: UserService = request.app[USER_SERVICE_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]
    transcript_service: TranscriptService = request.app[TRANSCRIPT_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response(
            create_error_response("User not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    try:
        vo = await summary_service.list_digests(
            user_id,
            transcript_service,
            file_id=req_dto.file_id,
            category_id=req_dto.category_id,
            limit=req_dto.limit,
            offset=req_dto.offset,
        )
        return web.json_response(vo.to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error listing digests")
        return SupernoteError.uncaught(err).to_response()


MAX_EXPORT_DIGESTS = 5_000


@dataclass
class _DigestExportQueryDTO(DataClassJSONMixin):
    """Query parameters DTO for `GET /api/extended/digests/export`."""

    file_id: int | None = field(metadata=field_options(alias="fileId"), default=None)
    category_id: str | None = field(
        metadata=field_options(alias="categoryId"), default=None
    )
    format: str = "markdown"


@routes.get("/api/extended/digests/export")
async def handle_export_digests(request: web.Request) -> web.Response:
    """Export matching Digests (including handwriting OCR transcripts) as Markdown."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = parse_query_dto(request, _DigestExportQueryDTO)
    except InvalidInputError as err:
        return err.to_response()

    export_format = (req_dto.format or "markdown").strip().lower()
    if export_format != "markdown":
        return InvalidInputError(
            f"Unsupported export format {export_format!r}; supported formats: markdown"
        ).to_response()

    user_service: UserService = request.app[USER_SERVICE_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]
    transcript_service: TranscriptService = request.app[TRANSCRIPT_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response(
            create_error_response("User not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    try:
        all_digests = []
        seen_ids: set[int] = set()
        offset = 0
        page_size = 200
        while len(all_digests) < MAX_EXPORT_DIGESTS:
            remaining = MAX_EXPORT_DIGESTS - len(all_digests)
            batch_limit = min(page_size, remaining)
            vo = await summary_service.list_digests(
                user_id,
                transcript_service,
                file_id=req_dto.file_id,
                category_id=req_dto.category_id,
                limit=batch_limit,
                offset=offset,
            )
            for item in vo.digests:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                all_digests.append(item)
            offset += len(vo.digests)
            if not vo.digests or len(vo.digests) < batch_limit or offset >= vo.total:
                break

        markdown = format_digests_markdown(all_digests)
        return web.Response(
            text=markdown,
            content_type="text/markdown",
            charset="utf-8",
            headers={"Content-Disposition": 'attachment; filename="digests.md"'},
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error exporting digests")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/file/summary/list")
async def handle_extended_file_summary_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/list
    # Purpose: Extended API to list summaries for a file.
    # TODO: Deprecate once Web UI and CLI callers migrate to GET /api/extended/digests.
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, WebSummaryListRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

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


@routes.post("/api/extended/file/summary/to/pdf")
async def handle_summary_to_pdf(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/to/pdf
    # Purpose: Render a summary's handwriting to PDF and return a signed download URL.
    # Response: PdfVO
    try:
        req_data = await parse_json_dto(request, DownloadSummaryDTO)
    except InvalidInputError as err:
        return err.to_response()
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]
    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

    try:
        summary = await summary_service.get_summary(user_email, req_data.id)
        await conversion_service.convert_summary_to_pdf(user_email, summary)
        signed_path = await url_signer.sign(
            f"/api/oss/summary/pdf/{req_data.id}", user=user_email, single_use=False
        )
        download_url = f"{get_request_base_url(request)}{signed_path}"
        return web.json_response(PdfVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/file/summary/to/png")
async def handle_summary_to_png(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/to/png
    # Purpose: Render a summary's handwriting to per-page PNGs and return signed download URLs.
    # Response: PngVO
    try:
        req_data = await parse_json_dto(request, DownloadSummaryDTO)
    except InvalidInputError as err:
        return err.to_response()
    user_email = request[REQUEST_USER_KEY]
    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]
    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

    try:
        summary = await summary_service.get_summary(user_email, req_data.id)
        page_numbers = await conversion_service.convert_summary_to_png(
            user_email, summary
        )
        base_url = get_request_base_url(request)
        png_pages = []
        for page_no in page_numbers:
            signed_path = await url_signer.sign(
                f"/api/oss/summary/png/{req_data.id}/{page_no}",
                user=user_email,
                single_use=False,
            )
            png_pages.append(PngPageVO(page_no=page_no, url=f"{base_url}{signed_path}"))
        return web.json_response(PngVO(png_page_vo_list=png_pages).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


async def _stream_summary_render(
    request: web.Request, page_no: int | None
) -> web.StreamResponse:
    """Verify a signed summary render URL and stream its cached PDF (or page PNG)."""
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]
    try:
        payload = await url_signer.verify(request.path_qs, consume=False)
    except SupernoteError as err:
        return err.to_response()

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=HTTPStatus.FORBIDDEN,
        )

    summary_service: SummaryService = request.app[SUMMARY_SERVICE_KEY]
    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    blob_storage: BlobStorage = request.app[BLOB_STORAGE_KEY]
    try:
        summary_id = int(request.match_info["summary_id"])
        summary = await summary_service.get_summary(user_email, summary_id)
        if page_no is None:
            kind = OSSTransferKind.PDF_EXPORT
            blob = await conversion_service.get_summary_pdf(user_email, summary)
        else:
            kind = OSSTransferKind.PNG_PREVIEW
            blob = await conversion_service.get_summary_png_page(
                user_email, summary, page_no
            )
        if not blob:
            raise FileNotFoundError(f"Summary {summary_id} render not cached")
        metadata = await blob_storage.get_metadata(CACHE_BUCKET, blob.storage_key)
    except SupernoteError as err:
        return err.to_response()
    except FileNotFoundError:
        return web.json_response(
            create_error_response("Summary render not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    return await stream_blob_response(
        request=request,
        blob_storage=blob_storage,
        bucket=CACHE_BUCKET,
        storage_key=blob.storage_key,
        file_name=blob.file_name,
        file_size=metadata.size,
        kind=kind,
    )


@routes.get("/api/oss/summary/pdf/{summary_id:\\d+}")
@public_route
async def handle_oss_summary_pdf_download(request: web.Request) -> web.StreamResponse:
    """Handle rendered summary handwriting PDF download from CACHE_BUCKET.

    Endpoint: GET /api/oss/summary/pdf/{summary_id}
    """
    return await _stream_summary_render(request, page_no=None)


@routes.get("/api/oss/summary/png/{summary_id:\\d+}/{page_no:\\d+}")
@public_route
async def handle_oss_summary_png_download(request: web.Request) -> web.StreamResponse:
    """Handle rendered summary handwriting page PNG download from CACHE_BUCKET.

    Endpoint: GET /api/oss/summary/png/{summary_id}/{page_no}
    """
    return await _stream_summary_render(
        request, page_no=int(request.match_info["page_no"])
    )


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register summary synchronization and extended summary HTTP routes on ``core.app``."""
    _ = registrar
    core.app.add_routes(routes)
