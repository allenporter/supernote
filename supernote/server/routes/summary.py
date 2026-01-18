import logging
import urllib.parse

from aiohttp import web

from supernote.models.base import BaseResponse
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    AddSummaryGroupVO,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    AddSummaryVO,
    DeleteSummaryDTO,
    DeleteSummaryGroupDTO,
    DeleteSummaryTagDTO,
    DownloadSummaryDTO,
    DownloadSummaryVO,
    QuerySummaryByIdVO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    QuerySummaryGroupVO,
    QuerySummaryMD5HashVO,
    QuerySummaryTagVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
    UpdateSummaryTagDTO,
    UploadSummaryApplyDTO,
    UploadSummaryApplyVO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.services.summary import SummaryService
from supernote.server.utils.paths import generate_inner_name
from supernote.server.utils.url_signer import UrlSigner

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
    except SupernoteError as err:
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
    except SupernoteError as err:
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
    except SupernoteError as err:
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
    except SupernoteError as err:
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
    except SupernoteError as err:
        return err.to_response()
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
    except SupernoteError as err:
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
    except SupernoteError as err:
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
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/add/summary/group")
async def handle_add_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/add/summary/group
    # Purpose: Add a new summary group.
    # Response: AddSummaryGroupVO
    req_data = AddSummaryGroupDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        group = await summary_service.add_group(user_email, req_data)
        return web.json_response(AddSummaryGroupVO(id=group.id).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/update/summary/group")
async def handle_update_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/update/summary/group
    # Purpose: Update an existing summary group.
    # Response: BaseResponse
    req_data = UpdateSummaryGroupDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        await summary_service.update_group(user_email, req_data)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/delete/summary/group")
async def handle_delete_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/delete/summary/group
    # Purpose: Delete a summary group.
    # Response: BaseResponse
    req_data = DeleteSummaryGroupDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        await summary_service.delete_group(user_email, req_data.id)
        return web.json_response(BaseResponse().to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/group")
async def handle_query_summary_group(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/group
    # Purpose: Query summary groups.
    # Response: QuerySummaryGroupVO
    req_data = QuerySummaryGroupDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        groups = await summary_service.list_groups(user_email, req_data)
        return web.json_response(
            QuerySummaryGroupVO(
                summary_do_list=groups,
                total_records=len(groups),
                total_pages=1,
                current_page=req_data.page or 1,
                page_size=req_data.size or 20,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/upload/apply/summary")
async def handle_upload_apply_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/apply/summary
    # Purpose: Apply for upload (signed URL).
    # Response: UploadSummaryApplyVO
    req_data = UploadSummaryApplyDTO.from_dict(await request.json())
    user_email = request["user"]

    try:
        url_signer: UrlSigner = request.app["url_signer"]

        # Generate inner name
        inner_name = generate_inner_name(req_data.file_name, req_data.equipment_no)
        encoded_name = urllib.parse.quote(inner_name)

        # Sign URLs
        full_path = f"/api/oss/upload?path={encoded_name}"
        full_url_path = await url_signer.sign(full_path, user=user_email)
        full_url = f"{request.scheme}://{request.host}{full_url_path}"

        part_path = f"/api/oss/upload/part?path={encoded_name}"
        part_url_path = await url_signer.sign(part_path, user=user_email)
        part_url = f"{request.scheme}://{request.host}{part_url_path}"

        return web.json_response(
            UploadSummaryApplyVO(
                full_upload_url=full_url,
                part_upload_url=part_url,
                inner_name=inner_name,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/download/summary")
async def handle_download_summary(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/download/summary
    # Purpose: Get signed download URL for binary content.
    # Response: DownloadSummaryVO
    req_data = DownloadSummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        summary = await summary_service.get_summary(user_email, req_data.id)
        if not summary.handwrite_inner_name:
            return web.json_response(
                BaseResponse(
                    success=False, error_msg="Handwriting data not found"
                ).to_dict(),
                status=404,
            )

        url_signer: UrlSigner = request.app["url_signer"]
        encoded_name = urllib.parse.quote(summary.handwrite_inner_name)
        download_path = f"/api/oss/download?path={encoded_name}"
        signed_path = await url_signer.sign(download_path, user=user_email)
        download_url = f"{request.scheme}://{request.host}{signed_path}"

        return web.json_response(DownloadSummaryVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/hash")
async def handle_query_summary_hash(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/hash
    # Purpose: Query summary lightweight info (hash/integrity).
    # Response: QuerySummaryMD5HashVO
    req_data = QuerySummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        infos = await summary_service.list_summary_infos(user_email, req_data)
        return web.json_response(
            QuerySummaryMD5HashVO(
                summary_info_vo_list=infos,
                total_records=len(infos),
                total_pages=1,
                current_page=req_data.page or 1,
                page_size=req_data.size or 20,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/query/summary/id")
async def handle_query_summary_id(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/query/summary/id
    # Purpose: Query full summaries by ID.
    # Response: QuerySummaryByIdVO
    req_data = QuerySummaryDTO.from_dict(await request.json())
    user_email = request["user"]
    summary_service: SummaryService = request.app["summary_service"]

    try:
        summaries = await summary_service.list_summaries_by_id(user_email, req_data)
        return web.json_response(
            QuerySummaryByIdVO(summary_do_list=summaries).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
