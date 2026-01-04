import logging
import urllib.parse
import uuid
from pathlib import Path

from aiohttp import web

from supernote.models.file import (
    CapacityVO,
    FileDeleteDTO,
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileListQueryDTO,
    FileMoveAndCopyDTO,
    FilePathQueryDTO,
    FileReNameDTO,
    FileUploadApplyDTO,
    FileUploadApplyLocalVO,
    FileUploadFinishDTO,
    FolderAddDTO,
    FolderListQueryDTO,
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


@routes.post("/api/file/path/query")
async def handle_path_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/path/query
    # Purpose: Resolve file path and ID path.
    # Response: FilePathQueryVO

    req_data = FilePathQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.get_path_info(user_email, req_data.id)
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

    results = await file_service.search_files(
        user_email, req_data.keyword, flatten=True
    )
    response = FileLabelSearchVO(entries=results)
    return web.json_response(response.to_dict())


@routes.post("/api/file/folder/add")
async def handle_folder_add(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/folder/add
    # Purpose: Create a new folder (Web).
    # Response: FolderVO

    req_data = FolderAddDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.create_directory_by_id(
        user_email, req_data.directory_id, req_data.file_name
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/folder/list/query")
async def handle_folder_list_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/folder/list/query
    # Purpose: Query details for a list of folders.
    # Response: FolderListQueryVO

    req_data = FolderListQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.get_folders_by_ids(
        user_email, req_data.directory_id, req_data.id_list
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/move")
async def handle_file_move_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/move
    # Purpose: Move files/folders (Web).
    # Response: BaseResponse

    req_data = FileMoveAndCopyDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.move_items(
        user_email, req_data.id_list, req_data.directory_id, req_data.go_directory_id
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/copy")
async def handle_file_copy_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/copy
    # Purpose: Copy files/folders (Web).
    # Response: BaseResponse

    req_data = FileMoveAndCopyDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.copy_items(
        user_email, req_data.id_list, req_data.directory_id, req_data.go_directory_id
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/rename")
async def handle_file_rename_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/rename
    # Purpose: Rename file/folder (Web).
    # Response: BaseResponse

    req_data = FileReNameDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.rename_item(
        user_email, req_data.id, req_data.new_name
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/delete")
async def handle_file_delete(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/delete
    # Purpose: Delete file/folder (Web).
    # Response: BaseResponse

    req_data = FileDeleteDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.delete_items(
        user_email, req_data.id_list, req_data.directory_id
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/upload/apply")
async def handle_file_upload_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/apply
    # Purpose: Request upload (Web).
    # Response: FileUploadApplyLocalVO

    req_data = FileUploadApplyDTO.from_dict(await request.json())
    url_signer = request.app["url_signer"]

    # Generate inner_name
    ext = "".join(Path(req_data.file_name).suffixes)
    inner_name = f"{uuid.uuid4()}{ext}"

    # Sign URL
    encoded_name = urllib.parse.quote(inner_name)
    path_to_sign = f"/api/oss/upload?object_name={encoded_name}"
    signed_path = url_signer.sign(path_to_sign)
    full_url = f"{request.scheme}://{request.host}{signed_path}"

    return web.json_response(
        FileUploadApplyLocalVO(
            full_upload_url=full_url,
            inner_name=inner_name,
        ).to_dict()
    )


@routes.post("/api/file/upload/finish")
async def handle_file_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/finish
    # Purpose: Complete upload (Web).
    # Response: BaseResponse

    req_data = FileUploadFinishDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.upload_finish_web(user_email, req_data)
    return web.json_response(response.to_dict())
