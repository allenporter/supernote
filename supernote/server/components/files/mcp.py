"""MCP platform setup exposing VFS browsing and staged upload tools.

Registers `list_files`, `prepare_upload`, and `commit_upload` onto
`McpRegistrar` via `async_setup_mcp`. Reuses `FileService.list_folder`,
`FileService.check_upload_apply_web`, signed `POST /api/oss/upload`, and
`FileService.upload_finish_web`.
"""

from __future__ import annotations

import datetime
import json
import secrets
import urllib.parse
from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.core import ServerCore
from supernote.server.events import bind_event_provenance
from supernote.server.exceptions import (
    FileNotFound,
    HashMismatch,
    InvalidPath,
    QuotaExceeded,
    SupernoteError,
)
from supernote.server.keys import URL_SIGNER_KEY
from supernote.server.services.file import FileEntity
from supernote.server.utils.paths import generate_inner_name

__all__ = ["UPLOAD_TICKET_TTL_SECONDS", "async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
_UPLOAD_TICKET_PREFIX = "mcp:upload:"
UPLOAD_TICKET_TTL_SECONDS = 900  # 15 minutes


def _serialize_file(entity: FileEntity) -> dict[str, Any]:
    """Serialize a `FileEntity` for MCP tool responses (stringifying 64-bit IDs)."""
    return {
        "file_id": str(entity.id),
        "parent_id": str(entity.parent_id),
        "name": entity.name,
        "path": f"/{entity.full_path}" if entity.full_path else "/",
        "is_folder": entity.is_folder,
        "size": entity.size,
        "md5": entity.md5,
        "create_time": entity.create_time,
        "update_time": entity.update_time,
    }


def _validate_file_name(file_name: str) -> str | None:
    """Validate a single-segment filename, returning an error message if invalid."""
    if not file_name or not file_name.strip():
        return "file_name must be non-empty."
    if "/" in file_name or "\\" in file_name or "\x00" in file_name:
        return f"Invalid file_name {file_name!r}: must be a single filename without path separators."
    if file_name in (".", ".."):
        return f"Invalid file_name {file_name!r}."
    return None


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register VFS browsing and staged upload tools onto `registrar`."""
    file_service = core.file_service
    user_service = core.user_service
    coordination = core.coordination

    async def _resolve_authenticated_user() -> tuple[int, str] | None:
        if (user_id := get_authenticated_user_id()) is None:
            return None
        user_do = await user_service.get_user_by_id(user_id)
        if user_do is None:
            return None
        return user_id, user_do.email

    async def list_files(
        ctx: Context,
        path: str = "/",
        recursive: bool = False,
    ) -> dict[str, Any]:
        """List files and folders in the authenticated user's Supernote cloud storage.

        Args:
            path: VFS folder path to list (default: `"/"`, e.g. `"/INBOX"`, `"/DOCUMENT"`).
            recursive: Include all nested descendants when True (default: False).
        """
        _ = ctx
        if (auth := await _resolve_authenticated_user()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        _, email = auth

        try:
            entities = await file_service.list_folder(email, path, recursive=recursive)
        except FileNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except InvalidPath as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        return {
            "success": True,
            "path": path,
            "items": [_serialize_file(e) for e in entities],
        }

    async def prepare_upload(
        ctx: Context,
        directory_path: str,
        file_name: str,
        size: int,
    ) -> dict[str, Any]:
        """Prepare a staged file upload and return a signed HTTP upload URL.

        Upload the raw file bytes out-of-band using HTTP `POST` (`multipart/form-data`
        with field name `"file"`) to `upload_url`, which returns `{"innerName", "md5"}`,
        then call `commit_upload(upload_token, md5)` to land the file in VFS and trigger
        device sync.

        TODO(#444): Currently commits overwrite existing files with the same name
        (matching `FileService.upload_finish_web`). Add `overwrite=False` support
        if non-destructive conflict rejection is needed.

        Args:
            directory_path: Existing target folder path (e.g. `"/INBOX"`, `"/DOCUMENT"`).
            file_name: Target filename without path separators (e.g. `"paper.pdf"`).
            size: File size in bytes (non-negative integer) for pre-flight quota checks.
        """
        _ = ctx
        if (auth := await _resolve_authenticated_user()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        user_id, email = auth

        if err_msg := _validate_file_name(file_name):
            return create_error_response(err_msg, ErrorCode.BAD_REQUEST).to_dict()
        if isinstance(size, bool) or size < 0:
            return create_error_response(
                "size must be a non-negative integer.", ErrorCode.BAD_REQUEST
            ).to_dict()

        dir_entity = await file_service.get_file_info(email, directory_path)
        if dir_entity is None:
            return create_error_response(
                f"Directory not found: {directory_path}", ErrorCode.NOT_FOUND
            ).to_dict()
        if not dir_entity.is_folder:
            return create_error_response(
                f"Target path is not a directory: {directory_path}",
                ErrorCode.BAD_REQUEST,
            ).to_dict()

        try:
            await file_service.check_upload_apply_web(
                email, dir_entity.id, file_name, size
            )
        except QuotaExceeded as err:
            return create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()

        url_signer = core.app[URL_SIGNER_KEY]
        inner_name = generate_inner_name(file_name, None)
        encoded_name = urllib.parse.quote(inner_name)
        signed_path = await url_signer.sign(
            f"/api/oss/upload?path={encoded_name}",
            user=email,
            expiration=datetime.timedelta(seconds=UPLOAD_TICKET_TTL_SECONDS),
        )
        upload_url = f"{core.config.base_url.rstrip('/')}{signed_path}"

        upload_token = secrets.token_urlsafe(32)
        ticket = json.dumps(
            {
                "user_id": user_id,
                "email": email,
                "directory_id": dir_entity.id,
                "file_name": file_name,
                "inner_name": inner_name,
            }
        )
        await coordination.set_value(
            f"{_UPLOAD_TICKET_PREFIX}{upload_token}",
            ticket,
            ttl=UPLOAD_TICKET_TTL_SECONDS,
        )

        return {
            "success": True,
            "upload_token": upload_token,
            "upload_url": upload_url,
            "method": "POST",
            "field_name": "file",
            "expires_in": UPLOAD_TICKET_TTL_SECONDS,
        }

    async def commit_upload(
        ctx: Context,
        upload_token: str,
        md5: str,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Commit a previously staged upload into VFS and trigger device sync.

        Args:
            upload_token: Token returned by `prepare_upload`.
            md5: Hex MD5 digest of the uploaded file (returned by `POST /api/oss/upload`).
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for uploading the file.
        """
        _ = ctx
        if (auth := await _resolve_authenticated_user()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        user_id, _ = auth

        if not upload_token or not upload_token.strip():
            return create_error_response(
                "upload_token must be non-empty.", ErrorCode.BAD_REQUEST
            ).to_dict()
        if not md5 or not md5.strip():
            return create_error_response(
                "md5 must be non-empty.", ErrorCode.BAD_REQUEST
            ).to_dict()

        ticket_key = f"{_UPLOAD_TICKET_PREFIX}{upload_token}"
        raw_ticket = await coordination.get_value(ticket_key)
        if raw_ticket is None:
            return create_error_response(
                "Upload token not found or expired.", ErrorCode.NOT_FOUND
            ).to_dict()

        ticket = json.loads(raw_ticket)
        if ticket["user_id"] != user_id:
            return create_error_response(
                "Upload token not found or expired.", ErrorCode.NOT_FOUND
            ).to_dict()

        try:
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                entity = await file_service.upload_finish_web(
                    user=ticket["email"],
                    directory_id=ticket["directory_id"],
                    file_name=ticket["file_name"],
                    md5=md5,
                    inner_name=ticket["inner_name"],
                )
        except FileNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except HashMismatch as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except QuotaExceeded as err:
            return create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        await coordination.delete_value(ticket_key)

        return {
            "success": True,
            "file": _serialize_file(entity),
        }

    registrar.add_tool(list_files)
    registrar.add_tool(prepare_upload)
    registrar.add_tool(commit_upload)
