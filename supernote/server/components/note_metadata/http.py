"""HTTP platform routes for structured `.note` metadata and signed title crop downloads.

Mounts onto the main `aiohttp` application via `async_setup_http`:
- User endpoint: `POST /api/extended/file/note/metadata`
- Signed download (`@public_route`): `GET /api/oss/title/{file_id}/{bitmap_md5}`
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.models.extended import WebNoteMetadataRequestDTO, WebNoteMetadataVO
from supernote.server.components.http import HttpRegistrar, parse_json_dto
from supernote.server.constants import CACHE_BUCKET
from supernote.server.core import ServerCore
from supernote.server.exceptions import InvalidInputError, SupernoteError
from supernote.server.keys import (
    REQUEST_USER_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.metrics import OSSTransferKind
from supernote.server.routes.decorators import public_route
from supernote.server.routes.oss import stream_blob_response, verify_signed_user
from supernote.server.services.user import UserService
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

from .service import NOTE_METADATA_SERVICE_KEY, NoteMetadataService

__all__ = [
    "async_setup_http",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/extended/file/note/metadata")
async def handle_extended_note_metadata(request: web.Request) -> web.Response:
    """Return structured notebook and per-page metadata for an active `.note` file."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, WebNoteMetadataRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

    user_service: UserService = request.app[USER_SERVICE_KEY]
    metadata_service: NoteMetadataService = request.app[NOTE_METADATA_SERVICE_KEY]

    try:
        user_id = await user_service.get_user_id(user_email)
    except ValueError:
        return web.json_response(
            create_error_response("User not found").to_dict(), status=404
        )

    try:
        metadata_vo: (
            WebNoteMetadataVO | None
        ) = await metadata_service.get_note_metadata(
            user_id=user_id,
            file_id=req_dto.file_id,
        )
    except Exception as err:
        logger.exception("Error fetching notebook metadata")
        return SupernoteError.uncaught(err).to_response()

    if metadata_vo is None:
        return web.json_response(
            create_error_response(
                f"No metadata found for notebook {req_dto.file_id}"
            ).to_dict(),
            status=404,
        )

    url_signer: UrlSigner = request.app[URL_SIGNER_KEY]
    base_url = get_request_base_url(request)
    for title in metadata_vo.titles:
        if title.bitmap_md5:
            signed_path = await url_signer.sign(
                f"/api/oss/title/{req_dto.file_id}/{title.bitmap_md5}",
                user=user_email,
                single_use=False,
            )
            title.image_url = f"{base_url}{signed_path}"
    return web.json_response(metadata_vo.to_dict())


@routes.get("/api/oss/title/{file_id}/{bitmap_md5}")
@public_route
async def handle_oss_title_download(request: web.Request) -> web.StreamResponse:
    """Stream a note title's handwriting crop PNG from a signed URL."""
    user_service: UserService = request.app[USER_SERVICE_KEY]
    metadata_service: NoteMetadataService = request.app[NOTE_METADATA_SERVICE_KEY]
    blob_storage = metadata_service.blob_storage
    bitmap_md5 = request.match_info["bitmap_md5"]
    try:
        user_email = await verify_signed_user(request)
    except SupernoteError as err:
        return err.to_response()
    try:
        user_id = await user_service.get_user_id(user_email)
    except ValueError:
        return _title_image_not_found()
    # `file_id` is part of the signed path, so it is always the integer we signed.
    png_key = await metadata_service.get_title_png_key(
        user_id=user_id,
        file_id=int(request.match_info["file_id"]),
        bitmap_md5=bitmap_md5,
    )
    if png_key is None:
        return _title_image_not_found()
    try:
        metadata = await blob_storage.get_metadata(CACHE_BUCKET, png_key)
    except FileNotFoundError:
        # Crop removed by a concurrent re-hash or purge since it was resolved.
        return _title_image_not_found()
    return await stream_blob_response(
        request=request,
        blob_storage=blob_storage,
        bucket=CACHE_BUCKET,
        storage_key=png_key,
        file_name=f"title_{bitmap_md5}.png",
        file_size=metadata.size,
        kind=OSSTransferKind.PNG_PREVIEW,
    )


def _title_image_not_found() -> web.Response:
    return web.json_response(
        create_error_response("Title image not found").to_dict(),
        status=HTTPStatus.NOT_FOUND,
    )


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register note metadata HTTP routes on ``registrar.router``."""
    _ = core
    registrar.router.add_routes(routes)
