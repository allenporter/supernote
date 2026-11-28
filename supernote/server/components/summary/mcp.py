"""MCP platform setup exposing the `list_digests` tool.

Registers `list_digests` onto `McpRegistrar` via `async_setup_mcp`, returning
the shared `supernote.models.extended.DigestListVO` payload produced by
`SummaryService.list_digests`.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.core import ServerCore

from .service import SUMMARY_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
_DEFAULT_LIMIT = 50


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `list_digests` onto `registrar`."""
    summary_service = core.app[SUMMARY_SERVICE_KEY]
    transcript_service = core.app[TRANSCRIPT_SERVICE_KEY]

    async def list_digests(
        ctx: Context,
        file_id: str | None = None,
        category_id: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List Supernote Digest entries with inline handwriting OCR transcripts.

        Args:
            file_id: Optional numeric file ID string to filter Digests for one document.
            category_id: Optional category/group UUID (`parent_unique_identifier`) to filter Digests.
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

        vo = await summary_service.list_digests(
            user_id,
            transcript_service,
            file_id=parsed_file_id,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )
        return vo.to_dict()

    registrar.add_tool(list_digests)
