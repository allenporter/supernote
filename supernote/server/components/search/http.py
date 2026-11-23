"""HTTP platform routes for semantic notebook search and structured transcripts.

Mounts two authenticated endpoints onto the main `aiohttp` application via
`async_setup_http`:

- `POST /api/extended/search`: Semantic vector search across notebook pages
  (`WebSearchRequestDTO` -> `WebSearchResponseVO`).
- `POST /api/extended/transcript`: Structured per-page OCR transcript retrieval
  (`WebTranscriptRequestDTO` -> `WebTranscriptResponseVO`).
"""

from __future__ import annotations

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.extended import (
    PageTranscriptVO,
    SearchResultVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import REQUEST_USER_KEY, USER_SERVICE_KEY
from supernote.server.services.user import UserService

from .service import SEARCH_SERVICE_KEY, SearchService

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


@routes.post("/api/extended/search")
async def handle_extended_search(request: web.Request) -> web.Response:
    """Serve semantic search across notebook content (`POST /api/extended/search`)."""
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
        req_dto = WebSearchRequestDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    search_service: SearchService = request.app[SEARCH_SERVICE_KEY]

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
    """Serve structured per-page notebook transcripts (`POST /api/extended/transcript`)."""
    user_email = request[REQUEST_USER_KEY]
    try:
        data = await request.json()
        req_dto = WebTranscriptRequestDTO.from_dict(data)
    except _PARSE_ERRORS as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    search_service: SearchService = request.app[SEARCH_SERVICE_KEY]

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


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register search and transcript HTTP routes on ``core.app``."""
    _ = registrar
    core.app.add_routes(routes)
