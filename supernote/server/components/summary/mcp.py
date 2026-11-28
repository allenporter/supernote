"""MCP platform setup exposing the `list_digests` tool.

Registers `list_digests` onto `McpRegistrar` via `async_setup_mcp`, combining
Digest excerpts and metadata from `SummaryService` with OCR transcripts of
handwritten `.mark` annotations from `TranscriptService`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.mcpserver import Context

from supernote.models.base import BaseResponse, ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.core import ServerCore

from .service import SUMMARY_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@dataclass
class DigestItemVO(DataClassJSONMixin):
    """Structured Digest entry returned by the `list_digests` MCP tool."""

    id: int = field(metadata=field_options(serialize=str))
    """Summary database ID."""

    file_id: int | None = field(
        metadata=field_options(alias="fileId", serialize=str), default=None
    )
    """Linked source file ID, if any."""

    name: str | None = None
    """Display name of the Digest."""

    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    """Source document path on the Supernote device."""

    content: str | None = None
    """Highlighted excerpt or text content."""

    comment: str | None = None
    """Typed text comment attached to the Digest."""

    handwrite_transcript: str | None = field(
        metadata=field_options(alias="handwriteTranscript"), default=None
    )
    """OCR transcript of the Digest's handwritten `.mark` annotation, if available."""

    tags: str | None = None
    """Comma-separated tag labels."""

    author: str | None = None
    """Source author metadata."""

    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    """Original creation timestamp in milliseconds."""

    update_time: int | None = field(
        metadata=field_options(alias="updateTime"), default=None
    )
    """Last update timestamp in milliseconds."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


@dataclass
class DigestListResponseVO(BaseResponse):
    """Response VO for `list_digests`."""

    digests: list[DigestItemVO] = field(default_factory=list)
    """Matching Digest entries with handwritten annotation transcripts."""

    total: int = 0
    """Number of Digest entries returned."""

    class Config(BaseConfig):
        serialize_by_alias = True


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `list_digests` onto `registrar`."""
    summary_service = core.app[SUMMARY_SERVICE_KEY]
    transcript_service = core.app[TRANSCRIPT_SERVICE_KEY]

    async def list_digests(
        ctx: Context,
        file_id: str | None = None,
        parent_unique_identifier: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List Supernote Digest highlights, comments, and transcribed handwritten marginalia.

        Args:
            file_id: Optional numeric file ID string to filter Digests for one document.
            parent_unique_identifier: Optional category/group UUID to filter Digests by category.
            limit: Maximum number of Digests to return (1-200, default 50).
            offset: Number of matching Digests to skip for pagination (default 0).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        parsed_file_id: int | None = None
        if file_id is not None:
            try:
                parsed_file_id = int(file_id)
            except ValueError:
                return create_error_response(
                    f"Invalid file_id '{file_id}': must be a numeric ID string.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()

        clamped_limit = max(1, min(limit, _MAX_LIMIT))
        clamped_offset = max(0, offset)
        summaries = await summary_service.list_summaries_for_user(
            user_id,
            file_id=parsed_file_id,
            parent_uuid=parent_unique_identifier,
            limit=clamped_limit,
            offset=clamped_offset,
        )
        total = await summary_service.count_summaries_for_user(
            user_id,
            file_id=parsed_file_id,
            parent_uuid=parent_unique_identifier,
        )
        summary_ids = [s.id for s in summaries if s.id is not None]
        transcripts = await transcript_service.get_summary_transcripts(
            user_id, summary_ids
        )

        items: list[DigestItemVO] = []
        for summary in summaries:
            if summary.id is None:
                continue
            transcript = transcripts.get(summary.id)
            transcript_text = (
                transcript.text
                if transcript is not None
                and summary.handwrite_md5
                and transcript.handwrite_md5 == summary.handwrite_md5
                else None
            )
            items.append(
                DigestItemVO(
                    id=summary.id,
                    file_id=summary.file_id,
                    name=summary.name,
                    source_path=summary.source_path,
                    content=summary.content,
                    comment=summary.comment_str,
                    handwrite_transcript=transcript_text,
                    tags=summary.tags,
                    author=summary.author,
                    creation_time=summary.creation_time,
                    update_time=summary.update_time,
                )
            )

        return DigestListResponseVO(digests=items, total=total).to_dict()

    registrar.add_tool(list_digests)
