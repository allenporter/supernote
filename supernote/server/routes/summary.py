import logging

from aiohttp import web

from supernote.models.base import BaseResponse
from supernote.models.summary import (
    AddSummaryTagDTO,
    AddSummaryTagVO,
    DeleteSummaryTagDTO,
    QuerySummaryTagVO,
    UpdateSummaryTagDTO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.services.summary import SummaryService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/file/add/summary/tag")
async def handle_add_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary/tag
    # Purpose: Add a new summary tag.
    # Response: AddSummaryTagVO
    req_data = AddSummaryTagDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        tag = await summary_service.add_tag(user_email, req_data.name)
        return web.json_response(AddSummaryTagVO(id=tag.id).to_dict())
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/update/summary/tag")
async def handle_update_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/update/summary/tag
    # Purpose: Update an existing summary tag.
    # Response: BaseResponse
    req_data = UpdateSummaryTagDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        success = await summary_service.update_tag(
            user_email, req_data.id, req_data.name
        )
        if not success:
            return web.json_response(
                BaseResponse(success=False, error_msg="Tag not found").to_dict(),
                status=404,
            )
        return web.json_response(BaseResponse().to_dict())
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/delete/summary/tag")
async def handle_delete_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/delete/summary/tag
    # Purpose: Delete a summary tag.
    # Response: BaseResponse
    req_data = DeleteSummaryTagDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        success = await summary_service.delete_tag(user_email, req_data.id)
        if not success:
            return web.json_response(
                BaseResponse(success=False, error_msg="Tag not found").to_dict(),
                status=404,
            )
        return web.json_response(BaseResponse().to_dict())
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/tag")
async def handle_query_summary_tag(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/tag
    # Purpose: Query summary tags.
    # Response: QuerySummaryTagVO
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        tags = await summary_service.list_tags(user_email)
        return web.json_response(QuerySummaryTagVO(summary_tag_do_list=tags).to_dict())
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
