"""MCP platform setup exposing the `get_notebook_transcript` tool.

Registers `get_notebook_transcript` onto `McpRegistrar` via `async_setup_mcp`,
backed by `TranscriptService`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mashumaro.config import BaseConfig
from mcp.server.mcpserver import Context

from supernote.models.base import BaseResponse, ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.core import ServerCore

from .service import TRANSCRIPT_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


@dataclass
class TranscriptResponseVO(BaseResponse):
    """Response VO for `get_notebook_transcript`."""

    transcript: str | None = None
    """Formatted transcript text, or `None` on error."""

    class Config(BaseConfig):
        serialize_by_alias = True


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `get_notebook_transcript` onto `registrar`."""
    transcript_service = core.app[TRANSCRIPT_SERVICE_KEY]

    async def get_notebook_transcript(
        ctx: Context,
        file_id: str,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve the full transcript or a page range for a notebook.

        Args:
            file_id: The ID of the notebook.
            start_index: 0-based start page index (inclusive).
            end_index: 0-based end page index (inclusive).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        try:
            parsed_file_id = int(file_id)
        except ValueError:
            return create_error_response(
                f"Invalid file_id '{file_id}': must be a numeric ID string.",
                ErrorCode.BAD_REQUEST,
            ).to_dict()

        transcript = await transcript_service.get_transcript(
            user_id=user_id,
            file_id=parsed_file_id,
            start_index=start_index,
            end_index=end_index,
        )
        if transcript is None:
            return create_error_response(
                f"No transcript found for notebook {file_id}.",
                ErrorCode.NOT_FOUND,
            ).to_dict()

        return TranscriptResponseVO(transcript=transcript).to_dict()

    registrar.add_tool(get_notebook_transcript)
