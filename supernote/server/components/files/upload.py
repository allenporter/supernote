"""Shared validation, serialization, and commit helpers for MCP and HTTP file uploads."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.events import bind_event_provenance
from supernote.server.exceptions import (
    FileAlreadyExists,
    FileNotFound,
    InvalidPath,
    SupernoteError,
)
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileEntity, FileService
from supernote.server.utils.paths import generate_inner_name

__all__ = [
    "MAX_UPLOAD_BYTES",
    "UPLOAD_TICKET_PREFIX",
    "UPLOAD_TOKEN_TTL_SECONDS",
    "commit_bytes_upload",
    "serialize_file",
    "validate_file_name",
    "validate_md5_hex",
    "validate_upload_target",
]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
UPLOAD_TOKEN_TTL_SECONDS = 300  # 5 minutes
UPLOAD_TICKET_PREFIX = "files:upload:"

_MD5_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def serialize_file(entity: FileEntity) -> dict[str, Any]:
    """Serialize a `FileEntity` for MCP and HTTP responses (stringifying 64-bit IDs)."""
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


def validate_file_name(file_name: str) -> str | None:
    """Validate a single-segment filename, returning an error message if invalid."""
    if not file_name or not file_name.strip():
        return "file_name must be non-empty."
    if file_name != file_name.strip():
        return (
            f"Invalid file_name {file_name!r}: "
            "must not have leading or trailing whitespace."
        )
    if "/" in file_name or "\\" in file_name or "\x00" in file_name:
        return (
            f"Invalid file_name {file_name!r}: "
            "must be a single filename without path separators."
        )
    if file_name in (".", ".."):
        return f"Invalid file_name {file_name!r}."
    return None


def validate_md5_hex(md5: str | None) -> tuple[str | None, str | None]:
    """Validate an optional 32-char hex MD5 string, returning `(normalized, error)`."""
    if md5 is None:
        return None, None
    cleaned = md5.strip()
    if not _MD5_HEX_RE.fullmatch(cleaned):
        return (
            None,
            f"Invalid expected_md5 {md5!r}: must be a 32-character hexadecimal MD5 digest.",
        )
    return cleaned.lower(), None


async def validate_upload_target(
    file_service: FileService,
    email: str,
    directory_path: str,
    file_name: str,
    *,
    overwrite: bool,
) -> FileEntity:
    """Resolve `directory_path` and verify no folder collision or overwrite conflict exists."""
    dir_entity = await file_service.get_file_info(email, directory_path)
    if dir_entity is None:
        raise FileNotFound(f"Directory not found: {directory_path}")
    if not dir_entity.is_folder:
        raise InvalidPath(f"Target path is not a directory: {directory_path}")

    target_path = (
        f"/{dir_entity.full_path}/{file_name}"
        if dir_entity.full_path
        else f"/{file_name}"
    )
    existing = await file_service.get_file_info(email, target_path)
    if existing is not None:
        if existing.is_folder:
            raise InvalidPath(f"Target path is an existing directory: {target_path}")
        if not overwrite:
            raise FileAlreadyExists(f"File already exists: {target_path}")
    return dir_entity


async def commit_bytes_upload(
    file_service: FileService,
    blob_storage: BlobStorage,
    *,
    email: str,
    directory_id: int,
    file_name: str,
    raw_bytes: bytes,
    overwrite: bool,
    cause_seq: str | None = None,
    reason: str | None = None,
) -> FileEntity:
    """Check quota, persist blob, and commit to VFS via `FileService.upload_finish_web`."""
    inner_name: str | None = None
    try:
        await file_service.check_upload_apply_web(
            email, directory_id, file_name, len(raw_bytes)
        )
        inner_name = generate_inner_name(file_name, None)
        md5 = hashlib.md5(raw_bytes).hexdigest()
        await blob_storage.put(USER_DATA_BUCKET, inner_name, raw_bytes)
        with bind_event_provenance(cause_seq=cause_seq, reason=reason):
            return await file_service.upload_finish_web(
                user=email,
                directory_id=directory_id,
                file_name=file_name,
                md5=md5,
                inner_name=inner_name,
                overwrite=overwrite,
            )
    except SupernoteError:
        if inner_name is not None:
            await file_service.cleanup_unreferenced_blobs({inner_name})
        raise
