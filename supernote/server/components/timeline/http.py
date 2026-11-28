"""HTTP platform routes for the cross-notebook page timeline.

Mounts onto the main `aiohttp` application via `async_setup_http`:
- `POST /api/extended/timeline/pages`
- `POST /api/extended/timeline/days`
"""

from __future__ import annotations

import logging

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.models.timeline import TimelineDaysRequestDTO, TimelinePagesRequestDTO
from supernote.server.components.http import HttpRegistrar, parse_json_dto
from supernote.server.constants import CACHE_BUCKET
from supernote.server.core import ServerCore
from supernote.server.exceptions import InvalidInputError, SupernoteError
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    COMPONENT_LOADER_KEY,
    REQUEST_USER_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_page_png_path
from supernote.server.utils.url_signer import UrlSigner, get_request_base_url

from .service import TIMELINE_SERVICE_KEY, TimelineService

__all__ = [
    "async_setup_http",
    "routes",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


async def _resolve_user_id(request: web.Request) -> tuple[str, int] | web.Response:
    user_email: str = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    try:
        return user_email, await user_service.get_user_id(user_email)
    except ValueError:
        return web.json_response(
            create_error_response("User not found").to_dict(), status=404
        )


@routes.post("/api/extended/timeline/pages")
async def handle_timeline_pages(request: web.Request) -> web.Response:
    """Return paginated page activity across all active notebooks."""
    try:
        req_dto = await parse_json_dto(request, TimelinePagesRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

    resolved_user = await _resolve_user_id(request)
    if isinstance(resolved_user, web.Response):
        return resolved_user
    user_email, user_id = resolved_user

    timeline_service: TimelineService = request.app[TIMELINE_SERVICE_KEY]
    try:
        result_vo = await timeline_service.list_pages(user_id, req_dto)
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error listing timeline pages")
        return SupernoteError.uncaught(err).to_response()

    if (
        request.app[COMPONENT_LOADER_KEY].get("conversion") is not None
        and result_vo.items
    ):
        url_signer: UrlSigner = request.app[URL_SIGNER_KEY]
        base_url = get_request_base_url(request)
        blob_storage: BlobStorage = request.app[BLOB_STORAGE_KEY]
        for item in result_vo.items:
            if not item.page_id:
                continue
            png_key = get_page_png_path(item.file_id, item.page_id)
            if await blob_storage.exists(CACHE_BUCKET, png_key):
                signed_path = await url_signer.sign(
                    f"/api/oss/png/{item.file_id}/{item.page_index}",
                    user=user_email,
                    single_use=False,
                )
                item.image_url = f"{base_url}{signed_path}"

    return web.json_response(result_vo.to_dict())


@routes.post("/api/extended/timeline/days")
async def handle_timeline_days(request: web.Request) -> web.Response:
    """Return per-day activity counts for calendar navigation."""
    try:
        req_dto = await parse_json_dto(request, TimelineDaysRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

    resolved_user = await _resolve_user_id(request)
    if isinstance(resolved_user, web.Response):
        return resolved_user
    _, user_id = resolved_user

    timeline_service: TimelineService = request.app[TIMELINE_SERVICE_KEY]
    try:
        result_vo = await timeline_service.list_days(user_id, req_dto)
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error listing timeline days")
        return SupernoteError.uncaught(err).to_response()

    return web.json_response(result_vo.to_dict())


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register timeline HTTP routes on ``registrar.router``."""
    _ = core
    registrar.router.add_routes(routes)
