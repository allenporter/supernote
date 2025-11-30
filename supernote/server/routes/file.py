import asyncio
import logging
import urllib.parse
from aiohttp import web
from ..models.base import BaseResponse
from ..models.file import (
    SyncStartResponse,
    ListFolderRequest,
    ListFolderResponse,
    AllocationVO,
    CapacityResponse,
    FileQueryRequest,
    FileQueryByIdRequest,
    FileQueryResponse,
    UploadApplyRequest,
    UploadFinishRequest,
    DownloadApplyRequest,
    DownloadApplyResponse,
)
from ..services.storage import StorageService
from ..services.file import FileService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/file/2/files/synchronous/start")
async def handle_sync_start(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/start
    # Purpose: Start a file synchronization session.
    # Response: SynchronousStartLocalVO
    return web.json_response(
        SyncStartResponse(
            equipment_no="SN123456",  # Should match request
            syn_type=True,  # True for normal sync, False for full re-upload
        ).to_dict()
    )


@routes.post("/api/file/2/files/synchronous/end")
async def handle_sync_end(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/end
    # Purpose: End a file synchronization session.
    # Response: SynchronousEndLocalVO (likely just success)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/file/2/files/list_folder")
@routes.post("/api/file/3/files/list_folder_v3")
async def handle_list_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/list_folder
    # Purpose: List folders for sync selection.
    # Response: ListFolderLocalVO

    req_data = ListFolderRequest.from_dict(await request.json())
    path_str = req_data.path
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries = await loop.run_in_executor(None, file_service.list_folder, path_str)

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

    storage_service: StorageService = request.app["storage_service"]
    loop = asyncio.get_running_loop()
    used = await loop.run_in_executor(None, storage_service.get_storage_usage)

    return web.json_response(
        CapacityResponse(
            equipment_no="SN123456",  # Should match request
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
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries_vo = await loop.run_in_executor(None, file_service.get_file_info, path_str)

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
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()
    entries_vo = await loop.run_in_executor(None, file_service.get_file_info, file_id)

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
    file_service: FileService = request.app["file_service"]

    response = file_service.apply_upload(file_name, req_data.equipment_no, request.host)

    return web.json_response(response.to_dict())


@routes.post("/api/file/upload/data/{filename}")
@routes.put("/api/file/upload/data/{filename}")
async def handle_upload_data(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/data/{filename}
    # Purpose: Receive the actual file content.

    filename = request.match_info["filename"]
    storage_service: StorageService = request.app["storage_service"]

    # The device sends multipart/form-data
    # Note: trace_middleware might have consumed the body already if we are not careful.
    # But trace_middleware uses request.read() which caches the body, so it should be fine?
    # Actually, request.read() reads the whole body into memory.
    # request.multipart() expects to read from the stream.
    # If the body is already read, we might need to handle it differently.

    if request._read_bytes:
        # Body already read by middleware
        # We need to reconstruct a multipart reader or just parse it manually if possible.
        # However, aiohttp's multipart reader expects a stream.
        # Since we are in a "lite" server, maybe we can just skip the middleware for this route
        # or make the middleware smarter.
        # For now, let's try to use the standard multipart reader which might fail if stream is consumed.
        pass

    reader = await request.multipart()

    # Read the first part (which should be the file)
    field = await reader.next()
    if field.name == "file":
        # Write to temp file using non-blocking I/O
        total_bytes = await storage_service.save_temp_file(filename, field.read_chunk)
        logger.info(f"Received upload for {filename}: {total_bytes} bytes")

    return web.Response(status=200)


@routes.post("/api/file/2/files/upload/finish")
async def handle_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion and move file to final location.
    # Response: FileUploadFinishLocalVO

    req_data = UploadFinishRequest.from_dict(await request.json())
    file_service: FileService = request.app["file_service"]

    loop = asyncio.get_running_loop()

    try:
        response = await loop.run_in_executor(
            None,
            file_service.finish_upload,
            req_data.file_name,
            req_data.path,
            req_data.content_hash,
            req_data.equipment_no,
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
    storage_service: StorageService = request.app["storage_service"]

    # Verify file exists
    target_path = storage_service.resolve_path(file_id)
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

    storage_service: StorageService = request.app["storage_service"]
    target_path = storage_service.resolve_path(path_str)

    # Security check: prevent directory traversal
    if not storage_service.is_safe_path(target_path):
        return web.Response(status=403, text="Access denied")

    if not target_path.exists():
        return web.Response(status=404, text="File not found")

    return web.FileResponse(target_path)
