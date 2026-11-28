"""MCP tools for browsing cloud folders, uploading documents, and managing files on a Supernote device.

AI clients use these tools to inspect folders like `/INBOX` or `/DOCUMENT`,
create new folders, deliver reading material (Markdown, text, or small
PDFs/EPUBs up to 10 MiB), and soft-delete files or folders to the recycle bin
so connected tablets stay in sync automatically.

All mutations delegate to `FileService`, enforcing user isolation, storage
quotas, system-directory protection, and publishing domain events for
real-time device sync.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.events import bind_event_provenance
from supernote.server.exceptions import (
    AccessDenied,
    FileAlreadyExists,
    FileNotFound,
    InvalidPath,
    QuotaExceeded,
    SupernoteError,
)
from supernote.server.services.file import FileEntity
from supernote.server.utils.paths import generate_inner_name

__all__ = ["MAX_INLINE_UPLOAD_BYTES", "async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
MAX_INLINE_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB


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
    if file_name != file_name.strip():
        return f"Invalid file_name {file_name!r}: must not have leading or trailing whitespace."
    if "/" in file_name or "\\" in file_name or "\x00" in file_name:
        return (
            f"Invalid file_name {file_name!r}: "
            "must be a single filename without path separators."
        )
    if file_name in (".", ".."):
        return f"Invalid file_name {file_name!r}."
    return None


def _validate_folder_path(path: str) -> str | None:
    """Validate a VFS folder path, returning an error message if invalid."""
    if not path or not path.strip():
        return "path must be non-empty."
    if "\\" in path or "\x00" in path:
        return f"Invalid folder path {path!r}."
    stripped = path.strip("/")
    if not stripped:
        return "Cannot create root directory."
    for seg in stripped.split("/"):
        if not seg or seg != seg.strip() or seg in (".", ".."):
            return f"Invalid path segment in folder path {path!r}."
    return None


def _decode_content(content: str, encoding: str) -> tuple[bytes | None, str | None]:
    """Decode inline upload content with pre-decode size bounds."""
    normalized = encoding.strip().lower()
    if normalized == "utf-8":
        if len(content) > MAX_INLINE_UPLOAD_BYTES:
            return None, f"Upload exceeds {MAX_INLINE_UPLOAD_BYTES} bytes limit."
        raw_bytes = content.encode("utf-8")
    elif normalized == "base64":
        max_b64_len = (MAX_INLINE_UPLOAD_BYTES * 4 // 3) + 4
        if len(content) > max_b64_len:
            return None, f"Upload exceeds {MAX_INLINE_UPLOAD_BYTES} bytes limit."
        try:
            raw_bytes = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            return None, "Invalid base64 content."
    else:
        return (
            None,
            f"Unsupported encoding {encoding!r}: expected 'utf-8' or 'base64'.",
        )

    if len(raw_bytes) > MAX_INLINE_UPLOAD_BYTES:
        return None, f"Upload exceeds {MAX_INLINE_UPLOAD_BYTES} bytes limit."
    return raw_bytes, None


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register VFS browsing and document upload tools onto `registrar`."""
    file_service = core.file_service
    user_service = core.user_service
    blob_storage = core.blob_storage

    async def _resolve_authenticated_email() -> str | None:
        if (user_id := get_authenticated_user_id()) is None:
            return None
        user_do = await user_service.get_user_by_id(user_id)
        return user_do.email if user_do is not None else None

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
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

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

    async def upload_document(
        ctx: Context,
        directory_path: str,
        file_name: str,
        content: str,
        encoding: str = "utf-8",
        overwrite: bool = False,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Upload a document to Supernote cloud storage and trigger device sync.

        Args:
            directory_path: Existing target folder path (e.g. `"/INBOX"`, `"/DOCUMENT"`).
            file_name: Target filename without path separators (e.g. `"brief.md"`, `"paper.pdf"`).
            content: File content as UTF-8 text or base64-encoded bytes (up to 10 MiB).
            encoding: Content encoding: `"utf-8"` (default) or `"base64"`.
            overwrite: Replace an existing file with the same name when True (default: False).
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for uploading the file.
        """
        _ = ctx
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if err_msg := _validate_file_name(file_name):
            return create_error_response(err_msg, ErrorCode.BAD_REQUEST).to_dict()

        raw_bytes, decode_err = _decode_content(content, encoding)
        if decode_err is not None or raw_bytes is None:
            return create_error_response(
                decode_err or "Invalid content.", ErrorCode.BAD_REQUEST
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

        target_path = (
            f"/{dir_entity.full_path}/{file_name}"
            if dir_entity.full_path
            else f"/{file_name}"
        )
        existing = await file_service.get_file_info(email, target_path)
        if existing is not None:
            if existing.is_folder:
                return create_error_response(
                    f"Target path is an existing directory: {target_path}",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()
            if not overwrite:
                return create_error_response(
                    f"File already exists: {target_path}",
                    ErrorCode.CONFLICT,
                ).to_dict()

        inner_name: str | None = None
        try:
            await file_service.check_upload_apply_web(
                email, dir_entity.id, file_name, len(raw_bytes)
            )
            inner_name = generate_inner_name(file_name, None)
            md5 = hashlib.md5(raw_bytes).hexdigest()
            await blob_storage.put(USER_DATA_BUCKET, inner_name, raw_bytes)
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                entity = await file_service.upload_finish_web(
                    user=email,
                    directory_id=dir_entity.id,
                    file_name=file_name,
                    md5=md5,
                    inner_name=inner_name,
                    overwrite=overwrite,
                )
        except FileAlreadyExists as err:
            return create_error_response(str(err), ErrorCode.CONFLICT).to_dict()
        except QuotaExceeded as err:
            return create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict()
        except SupernoteError as err:
            if inner_name is not None:
                await file_service.cleanup_unreferenced_blobs({inner_name})
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        return {
            "success": True,
            "file": _serialize_file(entity),
        }

    async def create_folder(
        ctx: Context,
        path: str,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create a directory path in Supernote cloud storage (creating missing parent folders).

        Args:
            path: Target VFS directory path (e.g. `"/DOCUMENT/Research"`).
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for creating the folder.
        """
        _ = ctx
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if err_msg := _validate_folder_path(path):
            return create_error_response(err_msg, ErrorCode.BAD_REQUEST).to_dict()

        try:
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                entity = await file_service.create_directory(email, path)
        except InvalidPath as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        return {
            "success": True,
            "folder": _serialize_file(entity),
        }

    async def delete_item(
        ctx: Context,
        file_id: str,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Move a file or folder to the recycle bin (soft delete) and trigger device sync.

        Protected Supernote system folders (such as `/INBOX`, `/DOCUMENT`, `/Note`)
        cannot be deleted.

        Args:
            file_id: Numeric VFS file or folder ID string (as returned by `list_files`).
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for deleting the item.
        """
        _ = ctx
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        try:
            parsed_id = int(file_id)
        except ValueError:
            return create_error_response(
                f"Invalid file_id {file_id!r}: must be a numeric ID string.",
                ErrorCode.BAD_REQUEST,
            ).to_dict()
        if parsed_id <= 0:
            return create_error_response(
                f"Invalid file_id {file_id!r}: must be a positive integer.",
                ErrorCode.BAD_REQUEST,
            ).to_dict()

        try:
            with bind_event_provenance(cause_seq=cause_seq, reason=reason):
                entity = await file_service.delete_item(email, parsed_id)
        except FileNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except AccessDenied as err:
            return create_error_response(str(err), ErrorCode.FORBIDDEN).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        return {
            "success": True,
            "deleted": _serialize_file(entity),
        }

    registrar.add_tool(list_files)
    registrar.add_tool(upload_document)
    registrar.add_tool(create_folder)
    registrar.add_tool(delete_item)
