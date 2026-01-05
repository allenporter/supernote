"""Handlers for the object storage service."""

import asyncio
import logging

from aiohttp import BodyPartReader, web

from supernote.models.base import create_error_response
from supernote.models.system import FileChunkParams, FileChunkVO, UploadFileVO
from supernote.server.services.file import FileService
from supernote.server.utils.url_signer import UrlSigner, UrlSignerError

from .decorators import public_route

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.post("/api/oss/upload")
@public_route
async def handle_oss_upload(request: web.Request) -> web.Response:
    """Handle OSS upload (device/v3).

    Query: object_name
    """
    file_service: FileService = request.app["file_service"]
    url_signer: UrlSigner = request.app["url_signer"]

    try:
        payload = url_signer.verify(request.path_qs)
    except UrlSignerError as err:
        return web.json_response(create_error_response(str(err)).to_dict(), status=403)

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=403,
        )

    # Extract object name/path from query params
    object_name = request.query.get("object_name")
    if not object_name:
        return web.json_response(
            create_error_response("Missing object_name", "E400").to_dict(), status=400
        )

    reader = await request.multipart()
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        total_bytes, md5_hash = await file_service.save_temp_file(
            user_email, object_name, field.read_chunk
        )
        logger.info(
            f"Received OSS upload for {object_name} (user: {user_email}): {total_bytes} bytes, MD5: {md5_hash}"
        )

        # Return UploadFileVO with innerName and md5
        response = UploadFileVO(
            inner_name=object_name,
            md5=md5_hash,
        )
        return web.json_response(response.to_dict())

    return web.Response(status=400, text="No file field found")


@routes.put("/api/oss/upload/part")
@routes.post("/api/oss/upload/part")
@public_route
async def handle_oss_upload_part(request: web.Request) -> web.Response:
    """Handle upload of a single part (chunk).

    Endpoint: POST /api/oss/upload/part
    Query Params: uploadId, partNumber, object_name, signature, totalChunks (optional/implied for implicit merge)
    """
    file_service: FileService = request.app["file_service"]
    url_signer: UrlSigner = request.app["url_signer"]

    try:
        payload = url_signer.verify(request.path_qs)
    except UrlSignerError as err:
        return web.json_response(create_error_response(str(err)).to_dict(), status=403)

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=403,
        )

    query_dict = dict(request.query)
    try:
        params = FileChunkParams.from_dict(query_dict)
    except ValueError:
        return web.json_response(
            create_error_response("Invalid param types", "E400").to_dict(), status=400
        )
    # Validate object_name which we added to model
    if not params.object_name:
        return web.json_response(
            create_error_response("Missing object_name", "E400").to_dict(), status=400
        )

    reader = await request.multipart()
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        total_bytes, chunk_md5 = await file_service.save_chunk_file(
            user_email,
            params.upload_id,
            params.object_name,
            params.part_number,
            field.read_chunk,
        )
        logger.info(
            f"Received chunk {params.part_number} for {params.object_name} (uploadId: {params.upload_id}): {total_bytes} bytes, MD5: {chunk_md5}"
        )

        # Implicit Merge Logic (for Device Compatibility)
        if params.total_chunks:
            if params.part_number == params.total_chunks:
                logger.info(
                    f"Implicitly merging {params.total_chunks} chunks for {params.object_name}"
                )
                await file_service.merge_chunks(
                    user_email,
                    params.upload_id,
                    params.object_name,
                    params.total_chunks,
                )
                await asyncio.to_thread(
                    file_service.cleanup_chunks, user_email, params.upload_id
                )
                logger.info(f"Successfully merged chunks for {params.object_name}")

        # Return FileChunkVO with chunk MD5
        resp_vo = FileChunkVO(
            upload_id=params.upload_id,
            part_number=params.part_number,
            total_chunks=params.total_chunks,
            chunk_md5=chunk_md5,
            status="success",
        )
        return web.json_response(resp_vo.to_dict())

    return web.Response(status=400, text="No file field")


@routes.get("/api/oss/download")
@public_route
async def handle_oss_download(request: web.Request) -> web.StreamResponse:
    """Handle file download with Range support.

    Endpoint: GET /api/oss/download
    Query Params: path (which effectively is the object key/ID), signature
    Headers: Range (optional)
    """
    url_signer: UrlSigner = request.app["url_signer"]
    file_service: FileService = request.app["file_service"]
    try:
        payload = url_signer.verify(request.path_qs)
    except UrlSignerError as err:
        return web.json_response(create_error_response(str(err)).to_dict(), status=403)

    # This takes the place of the authentication middlewhere.
    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=403,
        )

    file_id = request.query.get("id")
    if not file_id:
        return web.json_response(
            create_error_response("Missing id").to_dict(), status=400
        )

    # Resolve file metadata via VFS
    info = await file_service.get_file_info_by_id(user_email, int(file_id))
    if not info:
        return web.json_response(
            create_error_response("File not found").to_dict(), status=404
        )

    if info.is_folder:
        return web.json_response(
            create_error_response("Not a file").to_dict(), status=400
        )

    content_hash = info.md5
    if not content_hash:
        return web.json_response(
            create_error_response("File content not found").to_dict(), status=404
        )

    if not await file_service.blob_storage.exists(content_hash):
        return web.json_response(
            create_error_response("Blob not found").to_dict(), status=404
        )

    # Handle Range Header
    file_size = info.size
    range_header = request.headers.get("Range")

    start = 0
    end = file_size - 1

    if range_header:
        # Simplistic Range parsing: bytes=start-end
        try:
            unit, ranges = range_header.split("=")
            if unit == "bytes":
                r = ranges.split("-")
                if r[0]:
                    start = int(r[0])
                if len(r) > 1 and r[1]:
                    end = int(r[1])

                # Check bounds
                if start >= file_size:
                    return web.json_response(
                        create_error_response("Invalid range").to_dict(), status=416
                    )

                if end >= file_size:
                    end = file_size - 1
        except ValueError:
            return web.json_response(
                create_error_response("Invalid Range header").to_dict(), status=400
            )

    content_length = end - start + 1
    status = 206 if range_header else 200

    headers = {
        "Content-Disposition": f'attachment; filename="{info.name}"',
        "Content-Length": str(content_length),
        "Accept-Ranges": "bytes",
    }

    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)

    try:
        async with file_service.blob_storage.open_blob(content_hash) as f:
            if start > 0:
                await f.seek(start)

            bytes_to_send = content_length
            chunk_size = 8192

            while bytes_to_send > 0:
                read_size = min(chunk_size, bytes_to_send)
                chunk = await f.read(read_size)
                if not chunk:
                    break
                await response.write(chunk)
                bytes_to_send -= len(chunk)

    except FileNotFoundError:
        return web.json_response(
            create_error_response("Blob not found").to_dict(), status=404
        )

    return response
