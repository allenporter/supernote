"""HTTP platform routes for on-demand `.note` conversion and signed cache downloads.

Mounts:
- `POST /api/extended/file/note/cover`
- `POST /api/file/note/to/png`
- `POST /api/file/note/to/pdf`
- `GET /api/oss/png/{file_id}/{page_no}`
- `GET /api/oss/pdf/{file_id}`
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from http import HTTPStatus

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.models.extended import WebNoteCoverRequestDTO, WebNoteCoverVO
from supernote.models.file_device import PdfDTO, PdfVO, PngDTO, PngPageVO, PngVO
from supernote.server.components.http import HttpRegistrar, parse_json_dto
from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET
from supernote.server.core import ServerCore
from supernote.server.exceptions import AccessDenied, InvalidInputError, SupernoteError
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    CONFIG_KEY,
    REQUEST_USER_KEY,
    URL_SIGNER_KEY,
)
from supernote.server.metrics import OSSTransferKind
from supernote.server.routes.decorators import public_route
from supernote.server.routes.oss import stream_blob_response
from supernote.server.services.blob import BlobStorage
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

from . import CONVERSION_CONFIG_KEY
from .service import CONVERSION_SERVICE_KEY, ConversionService, ConvertedBlob

__all__ = [
    "async_setup_http",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/extended/file/note/cover")
async def handle_extended_note_cover(request: web.Request) -> web.Response:
    """Convert/fetch only the first page (page 0) PNG for lightweight explorer thumbnails."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, WebNoteCoverRequestDTO)
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    config: ServerConfig = request.app[CONFIG_KEY]
    conversion_cfg = request.app.get(CONVERSION_CONFIG_KEY)
    notebook_preview = (
        conversion_cfg.notebook_preview
        if conversion_cfg is not None
        else config.web_notebook_preview
    )
    if not (config.web_enabled and notebook_preview):
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


@routes.post("/api/file/note/to/png")
async def handle_note_to_png(request: web.Request) -> web.Response:
    """Convert a note to PNG pages and return signed `/api/oss/png/*` URLs."""
    try:
        req_data = await parse_json_dto(request, PngDTO)
    except InvalidInputError as err:
        return err.to_response()

    user_email = request[REQUEST_USER_KEY]
    config: ServerConfig = request.app[CONFIG_KEY]
    conversion_cfg = request.app.get(CONVERSION_CONFIG_KEY)
    notebook_preview = (
        conversion_cfg.notebook_preview
        if conversion_cfg is not None
        else config.web_notebook_preview
    )

    if not (config.web_enabled and notebook_preview):
        return web.json_response(PngVO(png_page_vo_list=[]).to_dict())

    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

    try:
        page_numbers = await conversion_service.convert_note_to_png(
            user_email, req_data.id
        )
        base_url = get_request_base_url(request)
        png_pages = []
        for page_no in page_numbers:
            path_to_sign = f"/api/oss/png/{req_data.id}/{page_no}"
            signed_path = await url_signer.sign(
                path_to_sign, user=user_email, single_use=False
            )
            download_url = f"{base_url}{signed_path}"
            png_pages.append(PngPageVO(page_no=page_no, url=download_url))

        return web.json_response(PngVO(png_page_vo_list=png_pages).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/note/to/pdf")
async def handle_note_to_pdf(request: web.Request) -> web.Response:
    """Convert a note to PDF and return a signed `/api/oss/pdf/*` URL."""
    try:
        req_data = await parse_json_dto(request, PdfDTO)
    except InvalidInputError as err:
        return err.to_response()

    user_email = request[REQUEST_USER_KEY]
    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]

    try:
        await conversion_service.convert_note_to_pdf(
            user_email, req_data.id, req_data.page_no_list
        )

        path_to_sign = f"/api/oss/pdf/{req_data.id}"
        if req_data.page_no_list:
            pages = ",".join(str(page_no) for page_no in req_data.page_no_list)
            path_to_sign += f"?pages={pages}"
        signed_path = await url_signer.sign(
            path_to_sign, user=user_email, single_use=False
        )
        base_url = get_request_base_url(request)
        download_url = f"{base_url}{signed_path}"

        return web.json_response(PdfVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


async def _verify_signed_user(
    request: web.Request,
    *,
    signed_query_keys: tuple[str, ...] = (),
) -> str:
    """Verify a signed cache-download URL and return the signed user email."""
    # TODO: Embed and verify numeric `user_id` instead of user email in UrlSigner
    # tokens to avoid leaking email in signed query params and extra DB lookups.
    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]
    payload = await url_signer.verify(
        request.path_qs, consume=False, signed_query_keys=signed_query_keys
    )
    user_email = payload.get("user")
    if not user_email:
        raise AccessDenied("Missing user identity in signature")
    return str(user_email)


async def _stream_cached_note_render(
    request: web.Request,
    *,
    resolve_blob: Awaitable[ConvertedBlob | None],
    not_found_message: str,
    kind: OSSTransferKind,
) -> web.StreamResponse:
    """Resolve and stream a previously converted `CACHE_BUCKET` blob."""
    blob_storage: BlobStorage = request.app[BLOB_STORAGE_KEY]

    try:
        blob = await resolve_blob
        if not blob:
            raise FileNotFoundError(not_found_message)
        metadata = await blob_storage.get_metadata(CACHE_BUCKET, blob.storage_key)
    except SupernoteError as err:
        return err.to_response()
    except FileNotFoundError:
        return web.json_response(
            create_error_response(not_found_message).to_dict(),
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


@routes.get("/api/oss/png/{file_id}/{page_no}")
@public_route
async def handle_oss_png_download(request: web.Request) -> web.StreamResponse:
    """Handle converted note page PNG download from CACHE_BUCKET."""
    try:
        user_email = await _verify_signed_user(request)
    except SupernoteError as err:
        return err.to_response()

    try:
        file_id = int(request.match_info["file_id"])
        page_no = int(request.match_info["page_no"])
    except (KeyError, ValueError):
        return web.json_response(
            create_error_response("Invalid file_id or page_no").to_dict(),
            status=HTTPStatus.BAD_REQUEST,
        )

    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    return await _stream_cached_note_render(
        request,
        resolve_blob=conversion_service.get_note_png_page(user_email, file_id, page_no),
        not_found_message="Page PNG not found",
        kind=OSSTransferKind.PNG_PREVIEW,
    )


@routes.get("/api/oss/pdf/{file_id}")
@public_route
async def handle_oss_pdf_download(request: web.Request) -> web.StreamResponse:
    """Handle converted note PDF download from CACHE_BUCKET."""
    try:
        user_email = await _verify_signed_user(request, signed_query_keys=("pages",))
    except SupernoteError as err:
        return err.to_response()

    try:
        file_id = int(request.match_info["file_id"])
        pages = request.query.get("pages")
        page_no_list = (
            [int(page_no) for page_no in pages.split(",")] if pages is not None else []
        )
    except (KeyError, ValueError):
        return web.json_response(
            create_error_response("Invalid file_id or pages").to_dict(),
            status=HTTPStatus.BAD_REQUEST,
        )

    conversion_service: ConversionService = request.app[CONVERSION_SERVICE_KEY]
    return await _stream_cached_note_render(
        request,
        resolve_blob=conversion_service.get_note_pdf(user_email, file_id, page_no_list),
        not_found_message="Note PDF not found",
        kind=OSSTransferKind.PDF_EXPORT,
    )


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register conversion HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
