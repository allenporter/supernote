"""MCP platform setup exposing notebook listing and semantic search tools.

Registers `list_notebooks` and `search_notebook_chunks` onto `McpRegistrar`
via `async_setup_mcp`, backed by `SearchService`.
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
from supernote.server.core import ServerCore

from .service import SEARCH_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


@dataclass
class NotebookVO(DataClassJSONMixin):
    """Serialized notebook metadata item returned by `list_notebooks`."""

    file_id: str = field(metadata=field_options(alias="fileId"))
    """Stringified VFS file identifier."""

    file_name: str = field(metadata=field_options(alias="fileName"))
    """Filename of the `.note` file."""

    create_time: int = field(metadata=field_options(alias="createTime"))
    """Creation timestamp in milliseconds since Unix epoch."""

    update_time: int = field(metadata=field_options(alias="updateTime"))
    """Last modification timestamp in milliseconds since Unix epoch."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListNotebooksResponseVO(BaseResponse):
    """Response VO for `list_notebooks`."""

    notebooks: list[NotebookVO] = field(default_factory=list)
    """Ordered list of active notebook metadata entries."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SearchResultVO(DataClassJSONMixin):
    """Serialized search hit returned by `search_notebook_chunks`."""

    file_id: str = field(metadata=field_options(alias="fileId"))
    """Stringified VFS file identifier."""

    file_name: str = field(metadata=field_options(alias="fileName"))
    """Filename of the matching `.note` file."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    """Zero-based page index."""

    page_id: str = field(metadata=field_options(alias="pageId"))
    """Supernote page identifier (`PAGEID`)."""

    score: float
    """Cosine similarity score."""

    text_preview: str = field(metadata=field_options(alias="textPreview"))
    """Preview snippet of the page OCR text."""

    date: str | None = None
    """Optional inferred page date (`YYYY-MM-DD`)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SearchResponseVO(BaseResponse):
    """Response VO for `search_notebook_chunks`."""

    results: list[SearchResultVO] = field(default_factory=list)
    """Ranked semantic search hits."""

    class Config(BaseConfig):
        serialize_by_alias = True


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `list_notebooks` and `search_notebook_chunks` onto `registrar`."""
    search_service = core.app[SEARCH_SERVICE_KEY]

    async def list_notebooks(
        ctx: Context,
        limit: int = 20,
        name_filter: str | None = None,
    ) -> dict[str, Any]:
        """List active notebooks ordered by most recently updated.

        Args:
            limit: Maximum number of notebooks to return (default: 20).
            name_filter: Optional substring filter for notebook filenames.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        notebooks = await search_service.list_notebooks(
            user_id=user_id,
            name_filter=name_filter,
            limit=limit,
        )
        vo_list = [
            NotebookVO(
                file_id=str(n.file_id),
                file_name=n.file_name,
                create_time=n.create_time,
                update_time=n.update_time,
            )
            for n in notebooks
        ]
        return ListNotebooksResponseVO(notebooks=vo_list).to_dict()

    async def search_notebook_chunks(
        ctx: Context,
        query: str,
        top_n: int = 5,
        name_filter: str | None = None,
        date_after: str | None = None,
        date_before: str | None = None,
    ) -> dict[str, Any]:
        """Search for notebook content chunks based on semantic similarity.

        Args:
            query: The semantic search query.
            top_n: Number of results to return (default: 5).
            name_filter: Optional substring filter for notebook filenames.
            date_after: Filter for notes created after this date (ISO 8601).
            date_before: Filter for notes created before this date (ISO 8601).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        results = await search_service.search_chunks(
            user_id=user_id,
            query=query,
            top_n=top_n,
            name_filter=name_filter,
            date_after=date_after,
            date_before=date_before,
        )
        vo_list = [
            SearchResultVO(
                file_id=str(r.file_id),
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

    registrar.add_tool(list_notebooks)
    registrar.add_tool(search_notebook_chunks)
