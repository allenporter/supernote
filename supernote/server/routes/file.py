import logging
import time
import urllib.parse

from aiohttp import web

from supernote.models.base import BaseResponse, create_error_response
from supernote.models.file import (
    AllocationVO,
    CapacityLocalVO,
    CreateFolderLocalDTO,
    DeleteFolderLocalDTO,
    FileCopyLocalDTO,
    FileDownloadLocalDTO,
    FileDownloadLocalVO,
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileMoveLocalDTO,
    FileQueryByPathLocalDTO,
    FileQueryByPathLocalVO,
    FileQueryLocalDTO,
    FileQueryLocalVO,
    FileUploadApplyLocalDTO,
    FileUploadApplyLocalVO,
    FileUploadFinishLocalDTO,
    ListFolderLocalDTO,
    ListFolderLocalVO,
    ListFolderV2DTO,
    RecycleFileDTO,
    RecycleFileListDTO,
    SynchronousEndLocalDTO,
    SynchronousEndLocalVO,
    SynchronousStartLocalDTO,
    SynchronousStartLocalVO,
)
from supernote.server.utils.url_signer import UrlSigner

from ..services.file import FileService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


SYNC_LOCK_TIMEOUT = 300  # 5 minutes


@routes.post("/api/file/2/files/synchronous/start")
async def handle_sync_start(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/start
    # Purpose: Start a file synchronization session.
    # Response: SynchronousStartLocalVO
    req_data = SynchronousStartLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    sync_locks = request.app["sync_locks"]
    sync_locks = request.app["sync_locks"]
    file_service: FileService = request.app["file_service"]

    is_empty = await file_service.is_empty(user_email)

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
        SynchronousStartLocalVO(
            equipment_no=req_data.equipment_no,
            syn_type=not is_empty,
        ).to_dict()
    )


@routes.post("/api/file/2/files/synchronous/end")
async def handle_sync_end(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/synchronous/end
    # Purpose: End a file synchronization session.
    # Response: SynchronousEndLocalVO
    req_data = SynchronousEndLocalDTO.from_dict(await request.json())
    user_email = request["user"]

    # Release lock
    sync_locks = request.app["sync_locks"]
    if user_email in sync_locks:
        owner_eq, _ = sync_locks[user_email]
        if owner_eq == req_data.equipment_no:
            del sync_locks[user_email]

    return web.json_response(SynchronousEndLocalVO().to_dict())


@routes.post("/api/file/2/files/list_folder")
async def handle_list_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/list_folder
    # Purpose: List folders for sync selection.
    # Response: ListFolderLocalVO

    req_data = ListFolderV2DTO.from_dict(await request.json())
    path_str = req_data.path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    entries = await file_service.list_folder(
        user_email,
        path_str,
        req_data.recursive,
    )

    return web.json_response(
        ListFolderLocalVO(equipment_no=req_data.equipment_no, entries=entries).to_dict()
    )


@routes.post("/api/file/3/files/list_folder_v3")
async def handle_list_folder_v3(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/list_folder_v3
    # Purpose: List folders by ID (Device V3).
    # Response: ListFolderLocalVO

    req_data = ListFolderLocalDTO.from_dict(await request.json())
    folder_id = req_data.id
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    entries = await file_service.list_folder_by_id(
        user_email,
        folder_id,
        req_data.recursive,
    )

    return web.json_response(
        ListFolderLocalVO(equipment_no=req_data.equipment_no, entries=entries).to_dict()
    )


@routes.post("/api/file/2/users/get_space_usage")
async def handle_capacity_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/users/get_space_usage
    # Purpose: Get storage capacity usage.
    # Response: CapacityLocalVO

    req_data = await request.json()
    equipment_no = req_data.get("equipmentNo", "")
    user_email = request["user"]

    file_service: FileService = request.app["file_service"]
    used = await file_service.get_storage_usage(user_email)

    return web.json_response(
        CapacityLocalVO(
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
    # Purpose: Check if a file exists by path (Device).
    # Response: FileQueryByPathLocalVO

    req_data = FileQueryByPathLocalDTO.from_dict(await request.json())
    path_str = req_data.path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    entries_vo = await file_service.get_file_info(user_email, path_str)
    if not entries_vo:
        return web.json_response(
            create_error_response(error_msg="File not found").to_dict(), status=404
        )

    return web.json_response(
        FileQueryByPathLocalVO(
            equipment_no=req_data.equipment_no,
            entries_vo=entries_vo,
        ).to_dict()
    )


@routes.post("/api/file/3/files/query_v3")
async def handle_query_v3(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/query_v3
    # Purpose: Get file details by ID (Device).
    # Response: FileQueryLocalVO

    req_data = FileQueryLocalDTO.from_dict(await request.json())
    file_id = req_data.id
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    entries_vo = await file_service.get_file_info(user_email, file_id)

    return web.json_response(
        FileQueryLocalVO(
            equipment_no=req_data.equipment_no,
            entries_vo=entries_vo,
        ).to_dict()
    )


@routes.post("/api/file/3/files/upload/apply")
async def handle_upload_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/upload/apply
    # Purpose: Request to upload a file.
    # Response: FileUploadApplyLocalVO

    req_data = FileUploadApplyLocalDTO.from_dict(await request.json())
    file_name = req_data.file_name

    url_signer: UrlSigner = request.app["url_signer"]

    encoded_name = urllib.parse.quote(file_name)

    # Simple Upload URL: /api/oss/upload?object_name={name}
    simple_path = f"/api/oss/upload?object_name={encoded_name}"
    full_upload_url_path = url_signer.sign(simple_path)
    full_upload_url = f"{request.scheme}://{request.host}{full_upload_url_path}"

    # Part Upload URL: /api/oss/upload/part?object_name={name}
    # Client will append &uploadId=...&partNumber=...
    part_path = f"/api/oss/upload/part?object_name={encoded_name}"
    part_upload_url_path = url_signer.sign(part_path)
    part_upload_url = f"{request.scheme}://{request.host}{part_upload_url_path}"

    return web.json_response(
        FileUploadApplyLocalVO(
            equipment_no=req_data.equipment_no or "",
            bucket_name="supernote-local",
            inner_name=file_name,
            x_amz_date="",
            authorization="",
            full_upload_url=full_upload_url,
            part_upload_url=part_upload_url,
        ).to_dict()
    )


@routes.post("/api/file/2/files/upload/finish")
async def handle_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion and move file to final location.
    # Response: FileUploadFinishLocalVO

    req_data = FileUploadFinishLocalDTO.from_dict(await request.json())
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
        # TODO: Update to use create_error_response
        return web.json_response(
            BaseResponse(success=False, error_msg="Upload not found").to_dict(),
            status=404,
        )
    except ValueError as err:
        # TODO: Update to use create_error_response
        return web.json_response(
            BaseResponse(
                success=False, error_msg=f"Failure processing upload: {err}"
            ).to_dict(),
            status=400,
        )

    return web.json_response(response.to_dict())


@routes.post("/api/file/3/files/download_v3")
async def handle_download_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/download_v3
    # Purpose: Request a download URL for a file.
    # Response: FileDownloadLocalVO

    req_data = FileDownloadLocalDTO.from_dict(await request.json())
    file_id = str(req_data.id)  # API Spec says int/str? Use str for path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    # Verify file exists using VFS
    info = await file_service.get_file_info(user_email, file_id)
    if not info:
        return web.json_response(
            BaseResponse(success=False, error_msg="File not found").to_dict(),
            status=404,
        )

    # Generate signed download URL
    url_signer: UrlSigner = request.app["url_signer"]

    encoded_id = urllib.parse.quote(info.id)
    # OSS download URL: /api/oss/download?path={id}
    path_to_sign = f"/api/oss/download?path={encoded_id}"

    # helper returns: ...?signature=...
    signed_path = url_signer.sign(path_to_sign)
    download_url = f"{request.scheme}://{request.host}{signed_path}"

    return web.json_response(
        FileDownloadLocalVO(
            equipment_no=req_data.equipment_no,
            url=download_url,
            id=info.id,
            name=info.name,
            path_display=info.path_display,
            content_hash=info.content_hash or "",
            size=info.size,
            is_downloadable=info.is_downloadable,
        ).to_dict()
    )


@routes.post("/api/file/2/files/create_folder_v2")
async def handle_create_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/create_folder_v2
    # Purpose: Create a new folder.
    # Response: CreateFolderLocalVO

    req_data = CreateFolderLocalDTO.from_dict(await request.json())
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
    # Response: DeleteFolderLocalVO

    req_data = DeleteFolderLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

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
    # Response: FileMoveLocalVO

    req_data = FileMoveLocalDTO.from_dict(await request.json())
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
    # Response: FileCopyLocalVO

    req_data = FileCopyLocalDTO.from_dict(await request.json())
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
