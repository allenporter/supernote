"""HTTP platform routes for structured per-page notebook transcripts.

Mounts `POST /api/extended/transcript` onto the main `aiohttp` application via
`async_setup_http` (`WebTranscriptRequestDTO` -> `WebTranscriptResponseVO`).
"""

from __future__ import annotations

import logging

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.models.extended import (
    PageTranscriptVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.server.components.http import HttpRegistrar, parse_json_dto
from supernote.server.core import ServerCore
from supernote.server.exceptions import InvalidInputError, SupernoteError
from supernote.server.keys import REQUEST_USER_KEY, USER_SERVICE_KEY
from supernote.server.services.user import UserService

from .service import TRANSCRIPT_SERVICE_KEY, TranscriptService

__all__ = [
    "async_setup_http",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/extended/transcript")
async def handle_extended_transcript(request: web.Request) -> web.Response:
    """Serve structured per-page notebook transcripts (`POST /api/extended/transcript`)."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = await parse_json_dto(request, WebTranscriptRequestDTO)
    except InvalidInputError as err:
        return err.to_response()

    user_service: UserService = request.app[USER_SERVICE_KEY]
    transcript_service: TranscriptService = request.app[TRANSCRIPT_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response(
            create_error_response("User not found").to_dict(), status=404
        )

    try:
        page_transcripts = await transcript_service.get_page_transcripts(
            user_id=user_id,
            file_id=req_dto.file_id,
            start_index=req_dto.start_index,
            end_index=req_dto.end_index,
        )
        title_transcripts = await transcript_service.get_title_transcripts(
            user_id=user_id,
            file_id=req_dto.file_id,
        )

        has_page_range = (
            req_dto.start_index is not None or req_dto.end_index is not None
        )
        if not page_transcripts and (has_page_range or not title_transcripts):
            return web.json_response(
                create_error_response(
                    f"No transcript found for notebook {req_dto.file_id}"
                ).to_dict(),
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

        return web.json_response(
            WebTranscriptResponseVO(
                pages=vo_pages,
                titles=title_transcripts,
            ).to_dict()
        )
    except Exception as err:
        logger.exception("Error fetching notebook transcript")
        return SupernoteError.uncaught(err).to_response()


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register transcript HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
