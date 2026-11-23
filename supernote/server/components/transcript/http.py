"""HTTP platform routes for structured per-page notebook transcripts.

Mounts `POST /api/extended/transcript` onto the main `aiohttp` application via
`async_setup_http` (`WebTranscriptRequestDTO` -> `WebTranscriptResponseVO`).
"""

from __future__ import annotations

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.extended import (
    PageTranscriptVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import REQUEST_USER_KEY, USER_SERVICE_KEY
from supernote.server.services.user import UserService

from .service import TRANSCRIPT_SERVICE_KEY, TranscriptService

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
    MissingField,
    InvalidFieldValue,
)


@routes.post("/api/extended/transcript")
async def handle_extended_transcript(request: web.Request) -> web.Response:
    """Serve structured per-page notebook transcripts (`POST /api/extended/transcript`)."""
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
        req_dto = WebTranscriptRequestDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    transcript_service: TranscriptService = request.app[TRANSCRIPT_SERVICE_KEY]

    if not (user_id := await user_service.get_user_id(user_email)):
        return web.json_response({"error": "User not found"}, status=404)

    try:
        page_transcripts = await transcript_service.get_page_transcripts(
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


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register transcript HTTP routes on ``core.app``."""
    _ = registrar
    core.app.add_routes(routes)
