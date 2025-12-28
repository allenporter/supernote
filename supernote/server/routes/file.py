import asyncio
import logging
import time
import urllib.parse

from aiohttp import BodyPartReader, web

from ..models.base import BaseResponse, create_error_response
from ..models.file import (
    AllocationVO,
    CapacityResponse,
    CreateDirectoryRequest,
    DeleteRequest,
    DownloadApplyRequest,
    DownloadApplyResponse,
    FileCopyRequest,
    FileMoveRequest,
    FileQueryByIdRequest,
    FileQueryRequest,
    FileQueryResponse,
    FileSearchRequest,
    FileSearchResponse,
    ListFolderRequest,
    ListFolderResponse,
    RecycleFileListRequest,
    RecycleFileRequest,
    SyncEndRequest,
    SyncStartRequest,
    SyncStartResponse,
    UploadApplyRequest,
    UploadFinishRequest,
)
from ..services.file import FileService
from ..services.storage import StorageService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


SYNC_LOCK_TIMEOUT = 300  # 5 minutes


@routes.post("/api/file/2/files/synchronous/start")
async def handle_sync_start(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/start
    # Purpose: Start a file synchronization session.
    # Response: SynchronousStartLocalVO
    req_data = SyncStartRequest.from_dict(await request.json())
    user_email = request["user"]
    sync_locks = request.app["sync_locks"]
    storage_service: StorageService = request.app["storage_service"]

    loop = asyncio.get_running_loop()
    is_empty = await loop.run_in_executor(None, storage_service.is_empty, user_email)

    now = time.time()
    if user_email in sync_locks:
        owner_eq, expiry = sync_locks[user_email]
        if now < expiry and owner_eq != req_data.equipment_no:
            logger.info(
                f"Sync conflict: user {user_email} already syncing from {owner_eq}"
            )
            return web.json_response(
                create_error_response(
                    error_msg="Another device is synchronizing",
                    error_code="E0078",
                ).to_dict(),
                status=409,
            )

    sync_locks[user_email] = (req_data.equipment_no, now + SYNC_LOCK_TIMEOUT)

    return web.json_response(
        SyncStartResponse(
            equipment_no=req_data.equipment_no,
            syn_type=not is_empty,
        ).to_dict()
    )


@routes.post("/api/file/2/files/synchronous/end")
async def handle_sync_end(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/end
    # Purpose: End a file synchronization session.
    req_data = SyncEndRequest.from_dict(await request.json())
    user_email = request["user"]

    # Release lock
    sync_locks = request.app["sync_locks"]
    if user_email in sync_locks:
        owner_eq, _ = sync_locks[user_email]
        if owner_eq == req_data.equipment_no:
            del sync_locks[user_email]

    return web.json_response(BaseResponse(success=True).to_dict())


@routes.post("/api/file/2/files/list_folder")
@routes.post("/api/file/3/files/list_folder_v3")
async def handle_list_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/list_folder
    # Purpose: List folders for sync selection.
    # Response: ListFolderLocalVO

    req_data = ListFolderRequest.from_dict(await request.json())
    path_str = req_data.path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries = await loop.run_in_executor(
        None, file_service.list_folder, user_email, path_str
    )

    return web.json_response(
        ListFolderResponse(
            equipment_no=req_data.equipment_no, entries=entries
        ).to_dict()
    )


@routes.post("/api/file/2/users/get_space_usage")
async def handle_capacity_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/users/get_space_usage
    # Purpose: Get storage capacity usage.
    # Response: CapacityLocalVO

    req_data = await request.json()
    equipment_no = req_data.get("equipmentNo", "")
    user_email = request["user"]

    storage_service: StorageService = request.app["storage_service"]
    loop = asyncio.get_running_loop()
    used = await loop.run_in_executor(
        None, storage_service.get_storage_usage, user_email
    )

    return web.json_response(
        CapacityResponse(
            equipment_no=equipment_no,
            used=used,
            allocation_vo=AllocationVO(
                tag="personal",
                allocated=1024 * 1024 * 1024 * 10,  # 10GB total
            ),
        ).to_dict()
    )


@routes.post("/api/file/3/files/query/by/path_v3")
async def handle_query_by_path(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/query/by/path_v3
    # Purpose: Check if a file exists by path.
    # Response: FileQueryByPathLocalVO

    req_data = FileQueryRequest.from_dict(await request.json())
    path_str = req_data.path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries_vo = await loop.run_in_executor(
        None, file_service.get_file_info, user_email, path_str
    )

    return web.json_response(
        FileQueryResponse(
            equipment_no=req_data.equipment_no,
            entries_vo=entries_vo,
        ).to_dict()
    )


@routes.post("/api/file/3/files/query_v3")
async def handle_query_v3(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/query_v3
    # Purpose: Get file details by ID.

    req_data = FileQueryByIdRequest.from_dict(await request.json())
    file_id = req_data.id
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries_vo = await loop.run_in_executor(
        None, file_service.get_file_info, user_email, file_id
    )

    return web.json_response(
        FileQueryResponse(
            equipment_no=req_data.equipment_no,
            entries_vo=entries_vo,
        ).to_dict()
    )


@routes.post("/api/file/3/files/upload/apply")
async def handle_upload_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/upload/apply
    # Purpose: Request to upload a file.
    # Response: FileUploadApplyLocalVO

    req_data = UploadApplyRequest.from_dict(await request.json())
    file_name = req_data.file_name
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.apply_upload(
        user_email, file_name, req_data.equipment_no or "", request.host
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/upload/data/{filename}")
@routes.put("/api/file/upload/data/{filename}")
async def handle_upload_data(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/data/{filename}
    # Purpose: Receive the actual file content.

    filename = request.match_info["filename"]
    user_email = request["user"]
    storage_service: StorageService = request.app["storage_service"]

    # The device sends multipart/form-data
    if request._read_bytes:
        # Body already read by middleware
        pass

    reader = await request.multipart()

    # Read the first part (which should be the file)
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        # Write to temp file using non-blocking I/O
        total_bytes = await storage_service.save_temp_file(
            user_email, filename, field.read_chunk
        )
        logger.info(
            f"Received upload for {filename} (user: {user_email}): {total_bytes} bytes"
        )

    return web.Response(status=200)


@routes.post("/api/file/2/files/upload/finish")
async def handle_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion and move file to final location.
    # Response: FileUploadFinishLocalVO

    req_data = UploadFinishRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()

    try:
        response = await loop.run_in_executor(
            None,
            file_service.finish_upload,
            user_email,
            req_data.file_name,
            req_data.path,
            req_data.content_hash,
            req_data.equipment_no or "",
        )
    except FileNotFoundError:
        return web.json_response(
            BaseResponse(success=False, error_msg="Upload not found").to_dict(),
            status=404,
        )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/download_v3")
async def handle_download_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/download_v3
    # Purpose: Request a download URL for a file.

    req_data = DownloadApplyRequest.from_dict(await request.json())
    file_id = req_data.id  # This is the relative path now
    user_email = request["user"]
    storage_service: StorageService = request.app["storage_service"]

    # Verify file exists
    target_path = storage_service.resolve_path(user_email, file_id)
    if not target_path.exists():
        return web.json_response(
            BaseResponse(success=False, error_msg="File not found").to_dict(),
            status=404,
        )

    # Generate URL
    encoded_id = urllib.parse.quote(file_id)
    download_url = f"http://{request.host}/api/file/download/data?path={encoded_id}"

    return web.json_response(DownloadApplyResponse(url=download_url).to_dict())


@routes.get("/api/file/download/data")
async def handle_download_data(request: web.Request) -> web.StreamResponse:
    # Endpoint: GET /api/file/download/data
    # Purpose: Download the file.

    path_str = request.query.get("path")
    if not path_str:
        return web.Response(status=400, text="Missing path")

    user_email = request["user"]
    storage_service: StorageService = request.app["storage_service"]
    target_path = storage_service.resolve_path(user_email, path_str)

    # Security check: prevent directory traversal
    if not storage_service.is_safe_path(user_email, target_path):
        return web.Response(status=403, text="Access denied")

    if not target_path.exists():
        return web.Response(status=404, text="File not found")

    return web.FileResponse(target_path)


@routes.post("/api/file/2/files/create_folder_v2")
async def handle_create_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/create_folder_v2
    # Purpose: Create a new folder.

    req_data = CreateDirectoryRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.create_directory(
        user_email,
        req_data.path,
        req_data.equipment_no,
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/delete_folder_v3")
async def handle_delete_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/delete_folder_v3
    # Purpose: Delete a file or folder.

    req_data = DeleteRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    # Request has 'id' (int) now
    response = file_service.delete_item(
        user_email,
        req_data.id,
        req_data.equipment_no,
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/move_v3")
async def handle_move_file(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/move_v3
    # Purpose: Move a file or folder.

    req_data = FileMoveRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.move_item(
        user_email,
        req_data.id,
        req_data.to_path,
        req_data.autorename,
        req_data.equipment_no,
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/copy_v3")
async def handle_copy_file(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/copy_v3
    # Purpose: Copy a file or folder.

    req_data = FileCopyRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.copy_item(
        user_email,
        req_data.id,
        req_data.to_path,
        req_data.autorename,
        req_data.equipment_no,
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/list/query")
async def handle_recycle_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/list/query
    # Purpose: List files in recycle bin.

    req_data = RecycleFileListRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.list_recycle(
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

    req_data = RecycleFileRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.delete_from_recycle(user_email, req_data.id_list)

    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/revert")
async def handle_recycle_revert(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/revert
    # Purpose: Restore items from recycle bin.

    req_data = RecycleFileRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.revert_from_recycle(user_email, req_data.id_list)

    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/clear")
async def handle_recycle_clear(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/clear
    # Purpose: Empty the recycle bin.

    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = file_service.clear_recycle(user_email)

    return web.json_response(response.to_dict())


@routes.post("/api/file/label/list/search")
async def handle_file_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/label/list/search
    # Purpose: Search for files by keyword.

    req_data = FileSearchRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    results = file_service.search_files(user_email, req_data.keyword)

    response = FileSearchResponse(entries=results)

    return web.json_response(response.to_dict())
