"""HTTP capability endpoint for single-use presigned binary uploads.

Handles `PUT /api/extended/uploads/{token}` for upload URLs minted by the MCP
`create_upload_url` tool. The high-entropy, short-lived, single-use token is
atomically consumed from `CoordinationService`, the raw binary request body is
streamed with a hard 10 MiB ceiling and optional size/MD5 verification, and the
file is committed through the same `FileService` + provenance path as
`upload_document`.
"""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus

from aiohttp import web

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.events import bind_event_actor
from supernote.server.exceptions import (
    FileAlreadyExists,
    QuotaExceeded,
    SupernoteError,
)
from supernote.server.routes.decorators import public_route

from .upload import (
    MAX_UPLOAD_BYTES,
    UPLOAD_TICKET_PREFIX,
    commit_bytes_upload,
    serialize_file,
)

__all__ = ["async_setup_http"]

_READ_CHUNK_BYTES = 64 * 1024  # 64 KiB


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register the single-use binary upload endpoint onto `registrar`."""
    routes = web.RouteTableDef()
    file_service = core.file_service
    blob_storage = core.blob_storage
    coordination = core.coordination

    @routes.put("/api/extended/uploads/{token}")
    @public_route
    async def handle_presigned_upload(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        raw_ticket = await coordination.pop_value(f"{UPLOAD_TICKET_PREFIX}{token}")
        if raw_ticket is None:
            return web.json_response(
                create_error_response(
                    "Upload token not found or expired.", ErrorCode.NOT_FOUND
                ).to_dict(),
                status=HTTPStatus.NOT_FOUND,
            )

        ticket = json.loads(raw_ticket)
        max_bytes = int(ticket.get("max_bytes", MAX_UPLOAD_BYTES))

        if (raw_cl := request.headers.get("Content-Length")) is not None:
            try:
                content_length = int(raw_cl)
            except ValueError:
                return web.json_response(
                    create_error_response(
                        "Invalid Content-Length header.", ErrorCode.BAD_REQUEST
                    ).to_dict(),
                    status=HTTPStatus.BAD_REQUEST,
                )
            if content_length > max_bytes:
                return web.json_response(
                    create_error_response(
                        f"Upload exceeds {max_bytes} bytes limit.",
                        ErrorCode.BAD_REQUEST,
                    ).to_dict(),
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )

        buf = bytearray()
        hasher = hashlib.md5()
        async for chunk in request.content.iter_chunked(_READ_CHUNK_BYTES):
            if len(buf) + len(chunk) > max_bytes:
                return web.json_response(
                    create_error_response(
                        f"Upload exceeds {max_bytes} bytes limit.",
                        ErrorCode.BAD_REQUEST,
                    ).to_dict(),
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            buf.extend(chunk)
            hasher.update(chunk)

        raw_bytes = bytes(buf)
        actual_size = len(raw_bytes)
        actual_md5 = hasher.hexdigest()

        expected_size = ticket.get("expected_size")
        if expected_size is not None and actual_size != expected_size:
            return web.json_response(
                create_error_response(
                    f"Upload size mismatch: expected {expected_size} bytes, got {actual_size} bytes.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict(),
                status=HTTPStatus.BAD_REQUEST,
            )

        expected_md5 = ticket.get("expected_md5")
        if expected_md5 is not None and actual_md5 != expected_md5:
            return web.json_response(
                create_error_response(
                    f"Upload MD5 mismatch: expected {expected_md5}, got {actual_md5}.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict(),
                status=HTTPStatus.BAD_REQUEST,
            )

        try:
            with bind_event_actor(ticket.get("actor")):
                entity = await commit_bytes_upload(
                    file_service,
                    blob_storage,
                    email=ticket["email"],
                    directory_id=ticket["directory_id"],
                    file_name=ticket["file_name"],
                    raw_bytes=raw_bytes,
                    overwrite=bool(ticket.get("overwrite", False)),
                    cause_seq=ticket.get("cause_seq"),
                    reason=ticket.get("reason"),
                )
        except FileAlreadyExists as err:
            return web.json_response(
                create_error_response(str(err), ErrorCode.CONFLICT).to_dict(),
                status=HTTPStatus.CONFLICT,
            )
        except QuotaExceeded as err:
            return web.json_response(
                create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict(),
                status=HTTPStatus.INSUFFICIENT_STORAGE,
            )
        except SupernoteError as err:
            return err.to_response()

        return web.json_response(
            {
                "success": True,
                "file": serialize_file(entity),
            }
        )

    registrar.router.add_routes(routes)
