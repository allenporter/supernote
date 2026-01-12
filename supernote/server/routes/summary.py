import logging

from aiohttp import web

from supernote.models.base import BaseResponse
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    AddSummaryVO,
    DeleteSummaryDTO,
    DeleteSummaryTagDTO,
    QuerySummaryDTO,
    QuerySummaryTagVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryTagDTO,
)
from supernote.server.exceptions import SummaryNotFound, SupernoteError
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
    except SummaryNotFound as err:
        return err.to_response()
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
        await summary_service.update_tag(user_email, req_data.id, req_data.name)
        return web.json_response(BaseResponse().to_dict())
    except SummaryNotFound as err:
        return err.to_response()
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
        await summary_service.delete_tag(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SummaryNotFound as err:
        return err.to_response()
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
    except SummaryNotFound as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/add/summary")
async def handle_add_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary
    # Purpose: Add a new summary.
    # Response: AddSummaryVO
    req_data = AddSummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        summary = await summary_service.add_summary(user_email, req_data)
        return web.json_response(AddSummaryVO(id=summary.id).to_dict())
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/update/summary")
async def handle_update_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/update/summary
    # Purpose: Update an existing summary.
    # Response: BaseResponse
    req_data = UpdateSummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        await summary_service.update_summary(user_email, req_data)
        return web.json_response(BaseResponse().to_dict())
    except SummaryNotFound as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/delete/summary")
async def handle_delete_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/delete/summary
    # Purpose: Delete a summary.
    # Response: BaseResponse
    req_data = DeleteSummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        await summary_service.delete_summary(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SummaryNotFound as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary")
async def handle_query_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary
    # Purpose: Query summaries.
    # Response: QuerySummaryVO
    req_data = QuerySummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        summaries = await summary_service.list_summaries(
            user_email,
            parent_uuid=req_data.parent_unique_identifier,
            ids=req_data.ids,
            page=req_data.page or 1,
            size=req_data.size or 20,
        )
        return web.json_response(
            QuerySummaryVO(
                summary_do_list=summaries,
                total_records=len(summaries),
                total_pages=1,
                current_page=req_data.page,
                page_size=req_data.size,
            ).to_dict()
        )
    except SummaryNotFound as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
