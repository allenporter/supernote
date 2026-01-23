import logging
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.mcp.models import (
    SearchRequestDTO,
    SearchResponseVO,
    SearchResultVO,
    TranscriptResponseVO,
)
from supernote.server.services.search import SearchService
from supernote.server.services.user import UserService

logger = logging.getLogger(__name__)

# FastMCP instance
mcp = FastMCP("Supernote Retrieval")

# Global services to be injected by the app
_services: dict[str, Any] = {
    "search_service": None,
    "user_service": None,
}


def set_services(search_service: SearchService, user_service: UserService) -> None:
    """Inject services into the MCP module."""
    _services["search_service"] = search_service
    _services["user_service"] = user_service


async def _get_auth_user_id(token: str | None) -> Optional[int]:
    """Verify token and return user_id."""
    user_service: UserService = _services["user_service"]

    if not user_service or not token:
        return None

    session = await user_service.verify_token(token)
    if not session:
        return None

    return await user_service.get_user_id(session.email)


@mcp.tool()
async def search_notebook_chunks(
    query: str,
    top_n: int = 5,
    name_filter: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
) -> dict[str, Any]:
    """
    Search for notebook content chunks based on semantic similarity.

    Args:
        query: The semantic search query.
        top_n: Number of results to return (default: 5).
        name_filter: Optional substring filter for notebook filenames.
        date_after: Filter for notes created after this date (ISO 8601).
        date_before: Filter for notes created before this date (ISO 8601).
    """
    search_service: SearchService = _services["search_service"]
    if not search_service:
        return create_error_response(
            "Services not initialized.", ErrorCode.INTERNAL_ERROR
        ).to_dict()

    user_id = await _get_auth_user_id(os.environ.get("SUPERNOTE_TOKEN"))
    if user_id is None:
        return create_error_response(
            "Authentication failed. Please set a valid SUPERNOTE_TOKEN.",
            ErrorCode.UNAUTHORIZED,
        ).to_dict()

    # Use the DTO to validate internally
    dto = SearchRequestDTO(
        query=query,
        top_n=top_n,
        name_filter=name_filter,
        date_after=date_after,
        date_before=date_before,
    )

    results = await search_service.search_chunks(
        user_id=user_id,
        query=dto.query,
        top_n=dto.top_n,
        name_filter=dto.name_filter,
        date_after=dto.date_after,
        date_before=dto.date_before,
    )

    if not results:
        return SearchResponseVO(results=[]).to_dict()

    vo_list = [
        SearchResultVO(
            file_id=r.file_id,
            file_name=r.file_name,
            page_index=r.page_index,
            page_id=r.page_id,
            score=r.score,
            text_preview=r.text_preview,
            date=r.date,
        )
        for r in results
    ]

    return SearchResponseVO(results=vo_list).to_dict()


@mcp.tool()
async def get_notebook_transcript(
    file_id: int,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
) -> dict[str, Any]:
    """
    Retrieve the full transcript or a page range for a notebook.

    Args:
        file_id: The ID of the notebook.
        start_index: 0-based start page index (inclusive).
        end_index: 0-based end page index (inclusive).
    """
    search_service: SearchService = _services["search_service"]
    if not search_service:
        return create_error_response(
            "Services not initialized.", ErrorCode.INTERNAL_ERROR
        ).to_dict()

    user_id = await _get_auth_user_id(os.environ.get("SUPERNOTE_TOKEN"))
    if user_id is None:
        return create_error_response(
            "Authentication failed. Please set a valid SUPERNOTE_TOKEN.",
            ErrorCode.UNAUTHORIZED,
        ).to_dict()

    transcript = await search_service.get_transcript(
        user_id=user_id,
        file_id=file_id,
        start_index=start_index,
        end_index=end_index,
    )

    if transcript is None:
        return create_error_response(
            f"No transcript found for notebook {file_id}.", ErrorCode.NOT_FOUND
        ).to_dict()

    return TranscriptResponseVO(transcript=transcript).to_dict()


async def run_server(port: int) -> None:
    """Run the FastMCP server with Streamable HTTP transport."""
    mcp.settings.port = port
    logger.info(f"Starting MCP server on port {port} using streamable-http...")
    await mcp.run_streamable_http_async()
