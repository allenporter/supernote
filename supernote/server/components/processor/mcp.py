"""MCP platform setup exposing the `get_page_image` tool.

Registers `get_page_image` onto `McpRegistrar` via `async_setup_mcp`, delegating
ownership checks, cache/on-demand rendering, and PNG normalization to
`ProcessorService.get_page_image`.
"""

from __future__ import annotations

import base64
import json

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, ImageContent, TextContent

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import McpRegistrar, get_authenticated_user_id
from supernote.server.core import ServerCore
from supernote.server.exceptions import FileError
from supernote.server.utils.image import DEFAULT_MAX_IMAGE_DIMENSION

from . import PROCESSOR_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


def _error_tool_result(message: str, code: ErrorCode) -> CallToolResult:
    """Build a structured error `CallToolResult` with `is_error=True`."""
    payload = json.dumps(create_error_response(message, code).to_dict())
    return CallToolResult(
        content=[TextContent(type="text", text=payload)],
        is_error=True,
    )


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `get_page_image` onto `registrar`."""
    processor_service = core.app[PROCESSOR_SERVICE_KEY]

    async def get_page_image(
        ctx: Context,
        file_id: str,
        page_index: int = 0,
        max_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION,
    ) -> CallToolResult:
        """Retrieve a rendered PNG image for a notebook page or standalone image file.

        Args:
            file_id: Numeric ID of the `.note` notebook or image file.
            page_index: 0-based page index (defaults to 0; must be 0 for standalone images).
            max_dimension: Maximum longest-edge pixel dimension (64..2048, default 1568).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return _error_tool_result(_AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED)

        try:
            parsed_file_id = int(file_id)
        except ValueError:
            return _error_tool_result(
                f"Invalid file_id '{file_id}': must be a numeric ID string.",
                ErrorCode.BAD_REQUEST,
            )

        try:
            page_image = await processor_service.get_page_image(
                user_id=user_id,
                file_id=parsed_file_id,
                page_index=page_index,
                max_dimension=max_dimension,
            )
        except ValueError as err:
            return _error_tool_result(str(err), ErrorCode.BAD_REQUEST)
        except FileError as err:
            return _error_tool_result(err.message, ErrorCode.INTERNAL_ERROR)

        if page_image is None:
            return _error_tool_result(
                f"Page {page_index} image not found for file {file_id}.",
                ErrorCode.NOT_FOUND,
            )

        summary = (
            f"File: {page_image.file_name} (file_id={file_id}, "
            f"page_index={page_image.page_index}, page_id={page_image.page_id}, "
            f"dimensions={page_image.width}x{page_image.height})"
        )
        return CallToolResult(
            content=[
                TextContent(type="text", text=summary),
                ImageContent(
                    type="image",
                    data=base64.b64encode(page_image.png_bytes).decode("ascii"),
                    mime_type="image/png",
                ),
            ]
        )

    registrar.add_tool(get_page_image)
