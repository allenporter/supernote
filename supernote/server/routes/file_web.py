import logging

from aiohttp import web

from supernote.models.file import (
    CapacityVO,
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileListQueryDTO,
    RecycleFileDTO,
    RecycleFileListDTO,
)
from supernote.server.services.file import FileService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/file/capacity/query")
async def handle_capacity_query_cloud(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/capacity/query
    # Purpose: Get storage capacity usage (Cloud).
    # Response: CapacityVO

    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    # TODO: Implement quota properly
    used = await file_service.get_storage_usage(user_email)
    return web.json_response(
        CapacityVO(
            used_capacity=used,
            total_capacity=1024 * 1024 * 1024 * 10,  # 10GB total
        ).to_dict()
    )


@routes.post("/api/file/recycle/list/query")
async def handle_recycle_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/list/query
    # Purpose: List files in recycle bin.

    req_data = RecycleFileListDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.list_recycle(
        user_email,
        req_data.order,
        req_data.sequence,
        req_data.page_no,
        req_data.page_size,
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/delete")
async def handle_recycle_delete(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/delete
    # Purpose: Permanently delete items from recycle bin.
    # Response: BaseVO

    req_data = RecycleFileDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.delete_from_recycle(user_email, req_data.id_list)
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/revert")
async def handle_recycle_revert(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/revert
    # Purpose: Restore items from recycle bin.
    # Response: BaseVO

    req_data = RecycleFileDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.revert_from_recycle(user_email, req_data.id_list)
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/clear")
async def handle_recycle_clear(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/clear
    # Purpose: Empty the recycle bin.

    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.clear_recycle(user_email)
    return web.json_response(response.to_dict())


@routes.post("/api/file/list/query")
async def handle_file_list_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/list/query
    # Purpose: Query files in a directory.
    # Response: FileListQueryVO

    req_data = FileListQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.query_file_list(
        user_email,
        req_data.directory_id,
        req_data.order,
        req_data.sequence,
        req_data.page_no,
        req_data.page_size,
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/label/list/search")
async def handle_file_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/label/list/search
    # Purpose: Search for files by keyword.
    # Response: FileSearchResponse

    req_data = FileLabelSearchDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    results = await file_service.search_files(user_email, req_data.keyword)
    response = FileLabelSearchVO(entries=results)
    return web.json_response(response.to_dict())
