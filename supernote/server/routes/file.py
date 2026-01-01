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

    is_empty = await asyncio.to_thread(storage_service.is_empty, user_email)

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

    entries = await file_service.list_folder(
        user_email,
        path_str,
        req_data.recursive,
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
    used = await asyncio.to_thread(storage_service.get_storage_usage, user_email)

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

    entries_vo = await file_service.get_file_info(user_email, path_str)

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

    entries_vo = await file_service.get_file_info(user_email, file_id)

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

    response = await asyncio.to_thread(
        file_service.apply_upload,
        user_email,
        file_name,
        req_data.equipment_no or "",
        request.host,
    )

    return web.json_response(response.to_dict())


@routes.post("/api/file/upload/data/{filename}")
@routes.put("/api/file/upload/data/{filename}")
async def handle_upload_data(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/data/{filename}
    # Purpose: Receive the actual file content (supports chunked uploads).

    filename = request.match_info["filename"]
    user_email = request["user"]
    storage_service: StorageService = request.app["storage_service"]

    # Check for chunked upload parameters
    upload_id = request.query.get("uploadId")
    total_chunks_str = request.query.get("totalChunks")
    part_number_str = request.query.get("partNumber")

    # The device sends multipart/form-data
    if request._read_bytes:
        # Body already read by middleware
        pass

    reader = await request.multipart()

    # Read the first part (which should be the file)
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        # Check if this is a chunked upload
        if upload_id and total_chunks_str and part_number_str:
            total_chunks = int(total_chunks_str)
            part_number = int(part_number_str)

            # Save this chunk
            total_bytes = await storage_service.save_chunk_file(
                user_email, upload_id, filename, part_number, field.read_chunk
            )
            logger.info(
                f"Received chunk {part_number}/{total_chunks} for {filename} "
                f"(user: {user_email}, uploadId: {upload_id}): {total_bytes} bytes"
            )

            # If this is the last chunk, merge all chunks
            if part_number == total_chunks:
                logger.info(
                    f"Received final chunk for {filename}, merging {total_chunks} chunks"
                )
                await storage_service.merge_chunks(
                    user_email,
                    upload_id,
                    filename,
                    total_chunks,
                )
                # Clean up chunk files
                await asyncio.to_thread(
                    storage_service.cleanup_chunks, user_email, upload_id
                )
                logger.info(f"Successfully merged and cleaned up chunks for {filename}")
        else:
            # Non-chunked upload
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

    try:
        response = await file_service.finish_upload(
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
    except ValueError:
        return web.json_response(
            BaseResponse(
                success=False, error_msg="Failure processing upload e.g. hash mismatch"
            ).to_dict(),
            status=400,
        )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/download_v3")
async def handle_download_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/download_v3
    # Purpose: Request a download URL for a file.

    req_data = DownloadApplyRequest.from_dict(await request.json())
    file_id = req_data.id  # This is the relative path or ID
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    # Verify file exists using VFS
    info = await file_service.get_file_info(user_email, file_id)
    if not info:
        return web.json_response(
            BaseResponse(success=False, error_msg="File not found").to_dict(),
            status=404,
        )

    # Generate URL
    # We pass the ID (or path) provided, or better: use the resolved ID if available?
    # Existing client expects "path=" query param to match what it sent?
    # Or we can send the ID back. Let's send what was requested to be safe for now,
    # OR send the stable ID if we want to move to IDs.
    # The ID passed to apply is usually what's used.
    # Let's stick to the input ID/path for the URL parameter to minimize client confusion,
    # BUT handle_download_data must be able to resolve it.

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
    file_service: FileService = request.app["file_service"]
    storage_service: StorageService = request.app["storage_service"]

    # 1. Resolve file metadata via VFS
    info = await file_service.get_file_info(user_email, path_str)
    if not info:
        return web.Response(status=404, text="File not found")

    if not info.is_downloadable or info.tag == "folder":
        return web.Response(status=400, text="Not a file")

    content_hash = info.content_hash
    if not content_hash:
        # Legacy fallback? Or empty file?
        # If size > 0 and no hash, it's an error in VFS migration?
        # Let's try to fallback to physical file if hash missing (migration compat).
        # Resolve physical path
        target_path = storage_service.resolve_path(user_email, path_str)
        if target_path.exists() and target_path.is_file():
            return web.FileResponse(target_path)
        return web.Response(status=404, text="File content not found")

    # 2. Check existence in BlobStorage
    if not await storage_service.blob_storage.exists(content_hash):
        # Fallback to physical path? (Hybrid mode)
        target_path = storage_service.resolve_path(user_email, path_str)
        if target_path.exists() and target_path.is_file():
            return web.FileResponse(target_path)

        return web.Response(status=404, text="Blob not found")

    # 3. Stream from BlobStorage
    # FileResponse expects a path. LocalBlobStorage stores as file.
    # We can get the path from BlobStorage if it exposes it.
    # LocalBlobStorage does.
    blob_path = storage_service.blob_storage.get_blob_path(content_hash)

    # Return file response with correct filename
    # We want "Content-Disposition: attachment; filename=..."
    # file_service.get_file_info returning info.name is useful here.

    return web.FileResponse(
        blob_path,
        headers={"Content-Disposition": f'attachment; filename="{info.name}"'},
    )


@routes.post("/api/file/2/files/create_folder_v2")
async def handle_create_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/create_folder_v2
    # Purpose: Create a new folder.

    req_data = CreateDirectoryRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.create_directory(
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
    response = await file_service.delete_item(
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

    response = await file_service.move_item(
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

    response = await file_service.copy_item(
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

    req_data = RecycleFileRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.delete_from_recycle(user_email, req_data.id_list)

    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/revert")
async def handle_recycle_revert(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/revert
    # Purpose: Restore items from recycle bin.

    req_data = RecycleFileRequest.from_dict(await request.json())
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


@routes.post("/api/file/label/list/search")
async def handle_file_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/label/list/search
    # Purpose: Search for files by keyword.

    req_data = FileSearchRequest.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    results = await file_service.search_files(user_email, req_data.keyword)

    response = FileSearchResponse(entries=results)

    return web.json_response(response.to_dict())
