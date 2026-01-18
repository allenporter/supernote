import logging
import time
import urllib.parse

from aiohttp import web

from supernote.models.base import BaseResponse, create_error_response
from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.models.file_device import (
    AllocationVO,
    CapacityLocalVO,
    CreateFolderLocalDTO,
    CreateFolderLocalVO,
    DeleteFolderLocalDTO,
    DeleteFolderLocalVO,
    EntriesVO,
    FileCopyLocalDTO,
    FileCopyLocalVO,
    FileDownloadLocalDTO,
    FileDownloadLocalVO,
    FileMoveLocalDTO,
    FileMoveLocalVO,
    FileQueryByPathLocalDTO,
    FileQueryByPathLocalVO,
    FileQueryLocalDTO,
    FileQueryLocalVO,
    FileUploadApplyLocalDTO,
    FileUploadFinishLocalDTO,
    FileUploadFinishLocalVO,
    ListFolderLocalDTO,
    ListFolderLocalVO,
    ListFolderV2DTO,
    MetadataVO,
    PdfDTO,
    PdfVO,
    PngDTO,
    PngPageVO,
    PngVO,
    SynchronousEndLocalDTO,
    SynchronousEndLocalVO,
    SynchronousStartLocalDTO,
    SynchronousStartLocalVO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.services.file import (
    FileEntity,
    FileService,
)
from supernote.server.utils.paths import generate_inner_name
from supernote.server.utils.url_signer import UrlSigner

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


def _to_entries_vo(entity: FileEntity) -> EntriesVO:
    """Convert FileEntity to EntriesVO."""
    return EntriesVO(
        tag=entity.tag,
        id=str(entity.id),
        name=entity.name,
        path_display=entity.full_path,
        parent_path=entity.parent_path,
        content_hash=entity.md5 or "",
        is_downloadable=True,
        size=entity.size,
        last_update_time=entity.update_time,
    )


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

    try:
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
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


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

    try:
        entities = await file_service.list_folder(
            user_email,
            path_str,
            req_data.recursive,
        )
        entries = [_to_entries_vo(e) for e in entities]

        return web.json_response(
            ListFolderLocalVO(
                equipment_no=req_data.equipment_no, entries=entries
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/3/files/list_folder_v3")
async def handle_list_folder_v3(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/list_folder_v3
    # Purpose: List folders by ID (Device V3).
    # Response: ListFolderLocalVO

    req_data = ListFolderLocalDTO.from_dict(await request.json())
    folder_id = req_data.id
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        entities = await file_service.list_folder_by_id(
            user_email,
            folder_id,
            req_data.recursive,
        )
        entries = [_to_entries_vo(e) for e in entities]

        return web.json_response(
            ListFolderLocalVO(
                equipment_no=req_data.equipment_no, entries=entries
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/2/users/get_space_usage")
async def handle_capacity_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/users/get_space_usage
    # Purpose: Get storage capacity usage.
    # Response: CapacityLocalVO

    req_data = await request.json()
    equipment_no = req_data.get("equipmentNo", "")
    user_email = request["user"]

    file_service: FileService = request.app["file_service"]
    try:
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
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/3/files/query/by/path_v3")
async def handle_query_by_path(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/query/by/path_v3
    # Purpose: Check if a file exists by path (Device).
    # Response: FileQueryByPathLocalVO

    req_data = FileQueryByPathLocalDTO.from_dict(await request.json())
    path_str = req_data.path
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        entity = await file_service.get_file_info(user_email, path_str)
        return web.json_response(
            FileQueryByPathLocalVO(
                equipment_no=req_data.equipment_no,
                entries_vo=_to_entries_vo(entity) if entity else None,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/3/files/query_v3")
async def handle_query_v3(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/query_v3
    # Purpose: Get file details by ID (Device).
    # Response: FileQueryLocalVO

    req_data = FileQueryLocalDTO.from_dict(await request.json())
    file_id = req_data.id
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        entity = await file_service.get_file_info_by_id(user_email, int(file_id))
        return web.json_response(
            FileQueryLocalVO(
                equipment_no=req_data.equipment_no,
                entries_vo=_to_entries_vo(entity) if entity else None,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/3/files/upload/apply")
async def handle_upload_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/upload/apply
    # Purpose: Request to upload a file.
    # Response: FileUploadApplyLocalVO

    req_data = FileUploadApplyLocalDTO.from_dict(await request.json())
    file_name = req_data.file_name

    try:
        url_signer: UrlSigner = request.app["url_signer"]

        # Generate a unique inner name for storage
        inner_name = generate_inner_name(file_name, req_data.equipment_no)
        encoded_name = urllib.parse.quote(inner_name)

        # Simple Upload URL: /api/oss/upload?path={name}&timestamp={ms}
        simple_path = f"/api/oss/upload?path={encoded_name}"
        full_upload_url_path = await url_signer.sign(simple_path, user=request["user"])
        full_upload_url = f"{request.scheme}://{request.host}{full_upload_url_path}"

        # Extract signature and timestamp using UrlSigner helpers
        signature = UrlSigner.extract_signature(full_upload_url_path)
        x_amz_date = UrlSigner.extract_timestamp(full_upload_url_path)
        if not signature or not x_amz_date:
            raise SupernoteError("Server generated invalid upload URL")

        # Part Upload URL: /api/oss/upload/part?path={name}
        # Client will append &uploadId=...&partNumber=...
        part_path = f"/api/oss/upload/part?path={encoded_name}"
        part_upload_url_path = await url_signer.sign(part_path, user=request["user"])
        part_upload_url = f"{request.scheme}://{request.host}{part_upload_url_path}"

        return web.json_response(
            FileUploadApplyLocalVO(
                equipment_no=req_data.equipment_no or "",
                bucket_name=file_name,  # Reference impl checks this matches filename
                inner_name=inner_name,
                x_amz_date=x_amz_date,
                authorization=signature,
                full_upload_url=full_upload_url,
                part_upload_url=part_upload_url,
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/2/files/upload/finish")
async def handle_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion and move file to final location.
    # Response: FileUploadFinishLocalVO

    req_data = FileUploadFinishLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    if not req_data.inner_name:
        return web.json_response(
            create_error_response("Invalid upload missing inner name").to_dict(),
            status=400,
        )

    try:
        entity = await file_service.finish_upload(
            user_email,
            req_data.file_name,
            req_data.path,
            req_data.content_hash,
            inner_name=req_data.inner_name,
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
    if not entity.md5:
        return web.json_response(
            create_error_response(error_msg="Invalid upload missing md5").to_dict(),
            status=500,
        )

    return web.json_response(
        FileUploadFinishLocalVO(
            equipment_no=req_data.equipment_no or "",
            path_display=entity.full_path,
            id=str(entity.id),
            size=entity.size,
            name=entity.name,
            content_hash=entity.md5 or "",
        ).to_dict()
    )


@routes.post("/api/file/3/files/download_v3")
async def handle_download_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/download_v3
    # Purpose: Request a download URL for a file.
    # Response: FileDownloadLocalVO

    req_data = FileDownloadLocalDTO.from_dict(await request.json())
    file_id = int(req_data.id)
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        # Verify file exists using VFS
        info = await file_service.get_file_info_by_id(user_email, file_id)
        if not info:
            return web.json_response(
                BaseResponse(success=False, error_msg="File not found").to_dict(),
                status=404,
            )

        # Generate signed download URL
        url_signer: UrlSigner = request.app["url_signer"]

        # OSS download URL: /api/oss/download?path={id}
        path_to_sign = f"/api/oss/download?path={info.id}"

        # helper returns: ...?signature=...
        signed_path = await url_signer.sign(path_to_sign, user=user_email)
        download_url = f"{request.scheme}://{request.host}{signed_path}"

    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()

    return web.json_response(
        FileDownloadLocalVO(
            equipment_no=req_data.equipment_no,
            url=download_url,
            id=str(info.id),
            name=info.name,
            path_display=info.full_path,
            content_hash=info.md5 or "",
            size=info.size,
            is_downloadable=True,
        ).to_dict()
    )


def _to_metadata_vo(entity: FileEntity) -> MetadataVO:
    return MetadataVO(
        name=entity.name,
        tag=entity.tag,
        id=str(entity.id),
        path_display=entity.full_path,
    )


@routes.post("/api/file/2/files/create_folder_v2")
async def handle_create_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/2/files/create_folder_v2
    # Purpose: Create a new folder.
    # Response: CreateFolderLocalVO

    req_data = CreateFolderLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        entry = await file_service.create_directory(user_email, req_data.path)
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
    return web.json_response(
        CreateFolderLocalVO(
            equipment_no=req_data.equipment_no,
            metadata=_to_metadata_vo(entry),
        ).to_dict()
    )


@routes.post("/api/file/3/files/delete_folder_v3")
async def handle_delete_folder(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/delete_folder_v3
    # Purpose: Delete a file or folder.
    # Response: DeleteFolderLocalVO

    req_data = DeleteFolderLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        deleted_item = await file_service.delete_item(
            user_email,
            req_data.id,
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()

    return web.json_response(
        DeleteFolderLocalVO(
            equipment_no=req_data.equipment_no,
            metadata=_to_metadata_vo(deleted_item),
        ).to_dict()
    )


@routes.post("/api/file/3/files/move_v3")
async def handle_move_file(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/move_v3
    # Purpose: Move a file or folder.
    # Response: FileMoveLocalVO

    req_data = FileMoveLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        result = await file_service.move_item(
            user_email,
            req_data.id,
            req_data.to_path,
            req_data.autorename,
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
    return web.json_response(
        FileMoveLocalVO(
            equipment_no=req_data.equipment_no,
            entries_vo=_to_entries_vo(result),
        ).to_dict()
    )


@routes.post("/api/file/3/files/copy_v3")
async def handle_copy_file(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/3/files/copy_v3
    # Purpose: Copy a file or folder.
    # Response: FileCopyLocalVO

    req_data = FileCopyLocalDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        result = await file_service.copy_item(
            user_email,
            req_data.id,
            req_data.to_path,
            req_data.autorename,
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
    return web.json_response(
        FileCopyLocalVO(
            equipment_no=req_data.equipment_no,
            entries_vo=_to_entries_vo(result),
        ).to_dict()
    )


@routes.post("/api/file/note/to/png")
async def handle_note_to_png(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/note/to/png
    # Purpose: Convert a note to PNG.
    # Response: PngVO
    req_data = PngDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]
    url_signer: UrlSigner = request.app["url_signer"]

    try:
        results = await file_service.convert_note_to_png(user_email, req_data.id)
        png_pages = []
        for res in results:
            # Generate signed URL for each PNG
            # OSS download URL: /api/oss/download?path={inner_name}
            # Here storage_key is already the full path within bucket
            path_to_sign = f"/api/oss/download?path={res.storage_key}"
            signed_path = await url_signer.sign(path_to_sign, user=user_email)
            download_url = f"{request.scheme}://{request.host}{signed_path}"

            png_pages.append(PngPageVO(page_no=res.page_no, url=download_url))

        return web.json_response(PngVO(png_page_vo_list=png_pages).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/file/note/to/pdf")
async def handle_note_to_pdf(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/note/to/pdf
    # Purpose: Convert a note to PDF.
    # Response: PdfVO
    req_data = PdfDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]
    url_signer: UrlSigner = request.app["url_signer"]

    try:
        storage_key = await file_service.convert_note_to_pdf(
            user_email, req_data.id, req_data.page_no_list
        )

        # Generate signed URL for PDF
        path_to_sign = f"/api/oss/download?path={storage_key}"
        signed_path = await url_signer.sign(path_to_sign, user=user_email)
        download_url = f"{request.scheme}://{request.host}{signed_path}"

        return web.json_response(PdfVO(url=download_url).to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()
