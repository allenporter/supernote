"""Local Object Storage Service (OSS) routes (`/api/oss/*`) for signed binary transfers.

Implements HMAC-signed (`supernote.server.utils.url_signer.UrlSigner`) upload and download
endpoints that emulate the cloud object storage layer expected by Supernote devices and the
Web UI:
- `POST /api/oss/upload`: Single-shot multipart file upload to `USER_DATA_BUCKET`.
- `POST /api/oss/upload/part` and `POST /api/oss/upload/complete`: Chunked multipart upload assembly.
- `GET /api/oss/download`: Byte-range streaming downloads from `USER_DATA_BUCKET` (`supernote.server.services.blob.BlobStorage`).
- `GET /api/oss/cache`: Signed delivery of cached PNGs and converted PDFs from `CACHE_BUCKET`.
- `POST /api/oss/summary/upload` and `GET /api/oss/summary/download`: Summary handwriting blob transfer.
"""

import asyncio
import logging
import mimetypes
from collections.abc import AsyncGenerator
from http import HTTPStatus
from pathlib import Path

from aiohttp import BodyPartReader, web

from supernote.models.base import create_error_response
from supernote.models.system import FileChunkParams, FileChunkVO, UploadFileVO
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.exceptions import SupernoteError
from supernote.server.services.blob import STREAM_CHUNK_SIZE, BlobStorage
from supernote.server.services.conversion import ConversionService
from supernote.server.services.file import FileService
from supernote.server.utils.paths import get_file_chunk_path
from supernote.server.utils.url_signer import UrlSigner

from .decorators import public_route

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


async def _stream_upload_field(field: BodyPartReader) -> AsyncGenerator[bytes]:
    """Stream chunks from a multipart field."""
    while True:
        chunk = await field.read_chunk(STREAM_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


@routes.post("/api/oss/upload")
@public_route
async def handle_oss_upload(request: web.Request) -> web.Response:
    """Handle OSS upload (device/v3).

    Query: object_name
    """
    url_signer: UrlSigner = request.app["url_signer"]
    blob_storage: BlobStorage = request.app["blob_storage"]

    logger.debug("OSS Upload Headers: %s", dict(request.headers))
    try:
        payload = await url_signer.verify(request.path_qs)
    except SupernoteError as err:
        return err.to_response()

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=403,
        )

    # Extract object name/path from query params
    object_name = request.query.get("path")
    if not object_name:
        return web.json_response(
            create_error_response("Missing path", "E400").to_dict(), status=400
        )

    if not request.content_type.startswith("multipart/"):
        return web.json_response(
            create_error_response(
                f"Expected multipart content, got {request.content_type}", "E400"
            ).to_dict(),
            status=400,
        )

    reader = await request.multipart()
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        metadata = await blob_storage.put(
            USER_DATA_BUCKET, object_name, _stream_upload_field(field)
        )
        logger.info(
            f"Received OSS upload for {object_name} (user: {user_email}): {metadata.size} bytes, MD5: {metadata.content_md5}"
        )

        # Return UploadFileVO with innerName and md5
        response = UploadFileVO(
            inner_name=object_name,
            md5=metadata.content_md5,
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
    url_signer: UrlSigner = request.app["url_signer"]
    blob_storage: BlobStorage = request.app["blob_storage"]

    logger.debug("OSS Upload Part Headers: %s", dict(request.headers))
    query_dict = dict(request.query)
    try:
        params = FileChunkParams.from_dict(query_dict)
    except ValueError:
        return web.json_response(
            create_error_response("Invalid param types", "E400").to_dict(), status=400
        )
    # Validate object_name which we added to model
    if not params.path:
        return web.json_response(
            create_error_response("Missing path", "E400").to_dict(), status=400
        )

    # Determine if this is the last chunk to consume the nonce
    should_consume = False
    if params.total_chunks and params.part_number == params.total_chunks:
        should_consume = True

    try:
        payload = await url_signer.verify(request.path_qs, consume=should_consume)
    except SupernoteError as err:
        return err.to_response()

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=403,
        )

    if not request.content_type.startswith("multipart/"):
        return web.json_response(
            create_error_response(
                f"Expected multipart content, got {request.content_type}", "E400"
            ).to_dict(),
            status=400,
        )

    reader = await request.multipart()
    field = await reader.next()
    if isinstance(field, BodyPartReader) and field.name == "file":
        chunk_key = get_file_chunk_path(params.path, params.part_number)

        metadata = await blob_storage.put(
            USER_DATA_BUCKET, chunk_key, _stream_upload_field(field)
        )
        chunk_md5 = metadata.content_md5
        total_bytes = metadata.size

        logger.info(
            f"Received chunk {params.part_number} for {params.path} (uploadId: {params.upload_id}): {total_bytes} bytes, MD5: {chunk_md5}"
        )

        # Implicit Merge Logic (for Device Compatibility)
        if params.total_chunks:
            if params.part_number == params.total_chunks:
                logger.info(
                    f"Implicitly merging {params.total_chunks} chunks for {params.path}"
                )
                source_keys = [
                    get_file_chunk_path(params.path, i)
                    for i in range(1, params.total_chunks + 1)
                ]

                async def combined_stream() -> AsyncGenerator[bytes]:
                    for source_key in source_keys:
                        async for chunk in blob_storage.get(
                            USER_DATA_BUCKET, source_key
                        ):
                            yield chunk

                await blob_storage.put(USER_DATA_BUCKET, params.path, combined_stream())
                logger.info(f"Successfully merged chunks for {params.path}")

                # Cleanup chunks
                await asyncio.gather(
                    *[blob_storage.delete(USER_DATA_BUCKET, key) for key in source_keys]
                )

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


_SAFE_INLINE_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/json",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "text/plain",
        "text/markdown",
        "text/csv",
    }
)


def _build_download_headers(
    file_name: str,
    file_size: int,
    start: int,
    end: int,
    *,
    is_range: bool,
    inline: bool,
) -> dict[str, str]:
    """Build HTTP response headers for an OSS file download."""
    content_length = end - start + 1
    guessed_type, _ = mimetypes.guess_type(file_name)
    content_type = guessed_type or "application/octet-stream"

    is_safe_inline_type = content_type in _SAFE_INLINE_MIME_TYPES
    disposition_type = "inline" if (inline and is_safe_inline_type) else "attachment"
    safe_file_name = (
        file_name.replace("\r", "")
        .replace("\n", "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    headers = {
        "Content-Type": content_type,
        "Content-Disposition": f'{disposition_type}; filename="{safe_file_name}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
        ),
        "Content-Length": str(content_length),
        "Accept-Ranges": "bytes",
    }
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return headers


async def _stream_blob_response(
    request: web.Request,
    blob_storage: BlobStorage,
    bucket: str,
    storage_key: str,
    file_name: str,
    file_size: int,
) -> web.StreamResponse:
    """Stream a blob from storage with HTTP Range and Content-Disposition support."""
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
                        create_error_response("Invalid range").to_dict(),
                        status=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                    )

                if end >= file_size:
                    end = file_size - 1
        except ValueError:
            return web.json_response(
                create_error_response("Invalid Range header").to_dict(),
                status=HTTPStatus.BAD_REQUEST,
            )

    status = HTTPStatus.PARTIAL_CONTENT if range_header else HTTPStatus.OK
    headers = _build_download_headers(
        file_name=file_name,
        file_size=file_size,
        start=start,
        end=end,
        is_range=bool(range_header),
        inline=request.query.get("inline") in ("1", "true"),
    )

    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)

    try:
        stream = blob_storage.get(bucket, storage_key, start=start, end=end)
        async for chunk in stream:
            await response.write(chunk)
    except FileNotFoundError:
        return web.json_response(
            create_error_response("Blob not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    return response


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
        payload = await url_signer.verify(request.path_qs, consume=False)
    except SupernoteError as err:
        return err.to_response()

    # This takes the place of the authentication middlewhere.
    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=HTTPStatus.FORBIDDEN,
        )

    file_id_str = request.query.get("path")
    if not file_id_str:
        return web.json_response(
            create_error_response("Missing path").to_dict(),
            status=HTTPStatus.BAD_REQUEST,
        )

    # Resolve file metadata
    try:
        # Try as numeric ID (legacy/sync flow)
        id_val = int(file_id_str)
        info = await file_service.get_file_info_by_id(user_email, id_val)
        if not info:
            return web.json_response(
                create_error_response("File not found").to_dict(),
                status=HTTPStatus.NOT_FOUND,
            )
        if info.is_folder:
            return web.json_response(
                create_error_response("Not a file").to_dict(),
                status=HTTPStatus.BAD_REQUEST,
            )
        storage_key = info.storage_key
        if not storage_key:
            return web.json_response(
                create_error_response("File content not found").to_dict(),
                status=HTTPStatus.NOT_FOUND,
            )
        file_name = info.name
        file_size = info.size
    except ValueError:
        # Treat as direct storage key in USER_DATA_BUCKET (summary handwriting flow)
        storage_key = file_id_str
        if not await file_service.blob_storage.exists(USER_DATA_BUCKET, storage_key):
            return web.json_response(
                create_error_response("Blob not found").to_dict(),
                status=HTTPStatus.NOT_FOUND,
            )
        metadata = await file_service.blob_storage.get_metadata(
            USER_DATA_BUCKET, storage_key
        )
        file_size = metadata.size
        file_name = Path(storage_key).name

    return await _stream_blob_response(
        request=request,
        blob_storage=file_service.blob_storage,
        bucket=USER_DATA_BUCKET,
        storage_key=storage_key,
        file_name=file_name,
        file_size=file_size,
    )


@routes.get("/api/oss/png/{file_id}/{page_no}")
@public_route
async def handle_oss_png_download(request: web.Request) -> web.StreamResponse:
    """Handle converted note page PNG download from CACHE_BUCKET.

    Endpoint: GET /api/oss/png/{file_id}/{page_no}
    """
    url_signer: UrlSigner = request.app["url_signer"]
    conversion_service: ConversionService = request.app["conversion_service"]
    blob_storage: BlobStorage = request.app["blob_storage"]
    try:
        payload = await url_signer.verify(request.path_qs, consume=False)
    except SupernoteError as err:
        return err.to_response()

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=HTTPStatus.FORBIDDEN,
        )

    try:
        file_id = int(request.match_info["file_id"])
        page_no = int(request.match_info["page_no"])
    except (KeyError, ValueError):
        return web.json_response(
            create_error_response("Invalid file_id or page_no").to_dict(),
            status=HTTPStatus.BAD_REQUEST,
        )

    try:
        blob = await conversion_service.get_note_png_page(user_email, file_id, page_no)
    except SupernoteError as err:
        return err.to_response()
    if not blob:
        return web.json_response(
            create_error_response("Page PNG not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    try:
        metadata = await blob_storage.get_metadata(CACHE_BUCKET, blob.storage_key)
    except FileNotFoundError:
        return web.json_response(
            create_error_response("Page PNG not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    return await _stream_blob_response(
        request=request,
        blob_storage=blob_storage,
        bucket=CACHE_BUCKET,
        storage_key=blob.storage_key,
        file_name=blob.file_name,
        file_size=metadata.size,
    )


@routes.get("/api/oss/pdf/{file_id}")
@public_route
async def handle_oss_pdf_download(request: web.Request) -> web.StreamResponse:
    """Handle converted note PDF download from CACHE_BUCKET.

    Endpoint: GET /api/oss/pdf/{file_id}
    """
    url_signer: UrlSigner = request.app["url_signer"]
    conversion_service: ConversionService = request.app["conversion_service"]
    blob_storage: BlobStorage = request.app["blob_storage"]
    try:
        payload = await url_signer.verify(request.path_qs, consume=False)
    except SupernoteError as err:
        return err.to_response()

    user_email = payload.get("user")
    if not user_email:
        return web.json_response(
            create_error_response("Missing user identity in signature").to_dict(),
            status=HTTPStatus.FORBIDDEN,
        )

    try:
        file_id = int(request.match_info["file_id"])
    except (KeyError, ValueError):
        return web.json_response(
            create_error_response("Invalid file_id").to_dict(),
            status=HTTPStatus.BAD_REQUEST,
        )

    try:
        blob = await conversion_service.get_note_pdf(user_email, file_id)
    except SupernoteError as err:
        return err.to_response()
    if not blob:
        return web.json_response(
            create_error_response("Note PDF not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    try:
        metadata = await blob_storage.get_metadata(CACHE_BUCKET, blob.storage_key)
    except FileNotFoundError:
        return web.json_response(
            create_error_response("Note PDF not found").to_dict(),
            status=HTTPStatus.NOT_FOUND,
        )

    return await _stream_blob_response(
        request=request,
        blob_storage=blob_storage,
        bucket=CACHE_BUCKET,
        storage_key=blob.storage_key,
        file_name=blob.file_name,
        file_size=metadata.size,
    )
