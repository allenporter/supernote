"""HTTP platform routes for semantic notebook search.

Mounts `POST /api/extended/search` onto the main `aiohttp` application via
`async_setup_http` (`WebSearchRequestDTO` -> `WebSearchResponseVO`).
"""

from __future__ import annotations

import json
import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.extended import (
    SearchResultVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
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

    if not (user_id := await user_service.get_user_id(user_email)):
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


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register search HTTP routes on ``core.app``."""
    _ = registrar
    core.app.add_routes(routes)
