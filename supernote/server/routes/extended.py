"""Module for server-specific extension routes.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

import logging

from aiohttp import web

from supernote.models.extended import WebSummaryListRequestDTO, WebSummaryListVO
from supernote.server.exceptions import SupernoteError
from supernote.server.services.summary import SummaryService

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
