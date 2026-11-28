"""MCP tools for browsing cloud folders, uploading documents, and managing files on a Supernote device.

AI clients use these tools to inspect folders like `/INBOX` or `/DOCUMENT`,
create new folders, deliver reading material (Markdown, text, or binary PDFs
up to 10 MiB), and soft-delete files or folders to the recycle bin so connected
tablets stay in sync automatically.

Two upload tools are provided:

- `upload_document`: single-call inline upload for UTF-8 text/Markdown (or small
  base64 payloads) with optional `expected_md5` verification.
- `create_upload_url`: mints a short-lived, single-use HTTP `PUT` URL so clients
  with outbound HTTP access can upload raw binary PDFs without passing base64
  through LLM tool-call arguments.

All mutations delegate to `FileService`, enforcing user isolation, storage
quotas, system-directory protection, and publishing domain events for
real-time device sync.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import json
import secrets
from collections.abc import Mapping
from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import (
    McpRegistrar,
    get_authenticated_actor,
    get_authenticated_user_id,
)
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

from .upload import (
    MAX_UPLOAD_BYTES,
    UPLOAD_TICKET_PREFIX,
    UPLOAD_TOKEN_TTL_SECONDS,
    commit_bytes_upload,
    serialize_file,
    validate_file_name,
    validate_md5_hex,
    validate_upload_target,
)

__all__ = ["MAX_INLINE_UPLOAD_BYTES", "async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
MAX_INLINE_UPLOAD_BYTES = MAX_UPLOAD_BYTES


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


def _resolve_public_base_url(
    configured_base_url: str | None,
    default_base_url: str,
    headers: Mapping[str, str] | None,
) -> str:
    """Resolve the externally reachable base URL for presigned HTTP upload links."""
    if configured_base_url is not None:
        return configured_base_url
    if headers is not None:
        fwd_host = headers.get("x-forwarded-host")
        if fwd_host:
            host = fwd_host.split(",")[0].strip()
            raw_proto = headers.get("x-forwarded-proto", "https")
            proto = raw_proto.split(",")[0].strip().lower()
            if (
                proto in ("http", "https")
                and host
                and "/" not in host
                and not any(c.isspace() for c in host)
            ):
                return f"{proto}://{host}".rstrip("/")
    return default_base_url


def _extract_request_headers(ctx: Context) -> Mapping[str, str] | None:
    """Safely extract HTTP headers from the active MCP request context, if available."""
    try:
        req = ctx.request_context.request
    except ValueError:
        return None
    headers = getattr(req, "headers", None)
    return headers if isinstance(headers, Mapping) else None


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register VFS browsing, management, and document upload tools onto `registrar`."""
    file_service = core.file_service
    user_service = core.user_service
    blob_storage = core.blob_storage
    coordination = core.coordination

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
            "items": [serialize_file(e) for e in entities],
        }

    async def upload_document(
        ctx: Context,
        directory_path: str,
        file_name: str,
        content: str,
        encoding: str = "utf-8",
        overwrite: bool = False,
        expected_md5: str | None = None,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Upload a document to Supernote cloud storage and trigger device sync.

        For binary files like PDFs from clients with outbound HTTP access, prefer
        `create_upload_url` + raw HTTP `PUT` to avoid base64 corruption in tool arguments.

        Args:
            directory_path: Existing target folder path (e.g. `"/INBOX"`, `"/DOCUMENT"`).
            file_name: Target filename without path separators (e.g. `"brief.md"`, `"paper.pdf"`).
            content: File content as UTF-8 text or base64-encoded bytes (up to 10 MiB).
            encoding: Content encoding: `"utf-8"` (default) or `"base64"`.
            overwrite: Replace an existing file with the same name when True (default: False).
            expected_md5: Optional 32-char hex MD5 digest to verify payload integrity.
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for uploading the file.
        """
        _ = ctx
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if err_msg := validate_file_name(file_name):
            return create_error_response(err_msg, ErrorCode.BAD_REQUEST).to_dict()

        normalized_md5, md5_err = validate_md5_hex(expected_md5)
        if md5_err is not None:
            return create_error_response(md5_err, ErrorCode.BAD_REQUEST).to_dict()

        raw_bytes, decode_err = _decode_content(content, encoding)
        if decode_err is not None or raw_bytes is None:
            return create_error_response(
                decode_err or "Invalid content.", ErrorCode.BAD_REQUEST
            ).to_dict()

        if normalized_md5 is not None:
            actual_md5 = hashlib.md5(raw_bytes).hexdigest()
            if actual_md5 != normalized_md5:
                return create_error_response(
                    f"Upload MD5 mismatch: expected {normalized_md5}, got {actual_md5}.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()

        try:
            dir_entity = await validate_upload_target(
                file_service, email, directory_path, file_name, overwrite=overwrite
            )
            entity = await commit_bytes_upload(
                file_service,
                blob_storage,
                email=email,
                directory_id=dir_entity.id,
                file_name=file_name,
                raw_bytes=raw_bytes,
                overwrite=overwrite,
                cause_seq=cause_seq,
                reason=reason,
            )
        except FileNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except InvalidPath as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except FileAlreadyExists as err:
            return create_error_response(str(err), ErrorCode.CONFLICT).to_dict()
        except QuotaExceeded as err:
            return create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        return {
            "success": True,
            "file": serialize_file(entity),
        }

    async def create_upload_url(
        ctx: Context,
        directory_path: str,
        file_name: str,
        expected_md5: str | None = None,
        expected_size: int | None = None,
        overwrite: bool = False,
        cause_seq: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Mint a single-use presigned HTTP `PUT` URL for raw binary document uploads.

        Send the raw file bytes directly with HTTP `PUT` (e.g.
        `curl -X PUT --data-binary @paper.pdf "<upload_url>"`) without any extra
        auth headers. On success, the HTTP `PUT` commits the file directly to VFS,
        triggers device sync, and returns `{"success": true, "file": {...}}`.

        Args:
            directory_path: Existing target folder path (e.g. `"/INBOX"`, `"/DOCUMENT"`).
            file_name: Target filename without path separators (e.g. `"paper.pdf"`).
            expected_md5: Optional 32-char hex MD5 digest verified before committing.
            expected_size: Optional exact byte length (`0..10485760`) verified before committing.
            overwrite: Replace an existing file with the same name when True (default: False).
            cause_seq: Optional causal domain event sequence ID for provenance tracking.
            reason: Optional human-readable reason for uploading the file.
        """
        if (email := await _resolve_authenticated_email()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        if err_msg := validate_file_name(file_name):
            return create_error_response(err_msg, ErrorCode.BAD_REQUEST).to_dict()

        normalized_md5, md5_err = validate_md5_hex(expected_md5)
        if md5_err is not None:
            return create_error_response(md5_err, ErrorCode.BAD_REQUEST).to_dict()

        if expected_size is not None:
            if isinstance(expected_size, bool) or expected_size < 0:
                return create_error_response(
                    "expected_size must be a non-negative integer.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()
            if expected_size > MAX_UPLOAD_BYTES:
                return create_error_response(
                    f"expected_size exceeds {MAX_UPLOAD_BYTES} bytes limit.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()

        try:
            dir_entity = await validate_upload_target(
                file_service, email, directory_path, file_name, overwrite=overwrite
            )
            if expected_size is not None and expected_size > 0:
                await file_service.check_upload_apply_web(
                    email, dir_entity.id, file_name, expected_size
                )
        except FileNotFound as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        except InvalidPath as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except FileAlreadyExists as err:
            return create_error_response(str(err), ErrorCode.CONFLICT).to_dict()
        except QuotaExceeded as err:
            return create_error_response(str(err), ErrorCode.QUOTA_EXCEEDED).to_dict()
        except SupernoteError as err:
            return create_error_response(str(err), ErrorCode.INTERNAL_ERROR).to_dict()

        token = secrets.token_urlsafe(32)
        expires_at = (
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=UPLOAD_TOKEN_TTL_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        ticket = json.dumps(
            {
                "email": email,
                "actor": get_authenticated_actor(),
                "directory_id": dir_entity.id,
                "file_name": file_name,
                "expected_md5": normalized_md5,
                "expected_size": expected_size,
                "overwrite": overwrite,
                "cause_seq": cause_seq,
                "reason": reason,
                "max_bytes": MAX_UPLOAD_BYTES,
            }
        )
        await coordination.set_value(
            f"{UPLOAD_TICKET_PREFIX}{token}",
            ticket,
            ttl=UPLOAD_TOKEN_TTL_SECONDS,
        )

        base_url = _resolve_public_base_url(
            core.config.configured_base_url,
            core.config.base_url,
            _extract_request_headers(ctx),
        )
        return {
            "success": True,
            "upload_url": f"{base_url}/api/extended/uploads/{token}",
            "method": "PUT",
            "expires_at": expires_at,
            "max_bytes": MAX_UPLOAD_BYTES,
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
            "folder": serialize_file(entity),
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
            "deleted": serialize_file(entity),
        }

    registrar.add_tool(list_files)
    registrar.add_tool(upload_document)
    registrar.add_tool(create_upload_url)
    registrar.add_tool(create_folder)
    registrar.add_tool(delete_item)
