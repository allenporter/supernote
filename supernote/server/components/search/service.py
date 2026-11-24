"""Semantic vector search and notebook listing service.

`SearchService` orchestrates `EmbeddingChunkSearcher` (`supernote.server.components.search.chunk_search`)
across active `.note` pages, supporting filename substring filters and `YYYY-MM-DD` date
bounds (`infer_page_date`), alongside active `.note` notebook listing.

### Internal Component Access

Other server components or plugins declaring ``dependencies = ("search",)``
retrieve the shared service instance via `core.app[SEARCH_SERVICE_KEY]`.
"""

from __future__ import annotations

import logging
from datetime import date

from aiohttp import web
from sqlalchemy import select

from supernote.server.ai.models.embedding import EmbeddingModel
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager

from .chunk_search import EmbeddingChunkSearcher, SearchQuery
from .models import NotebookInfo, SearchResult

__all__ = [
    "SEARCH_SERVICE_KEY",
    "SearchService",
]

logger = logging.getLogger(__name__)

_MAX_NOTEBOOK_LIMIT = 500
_MAX_TOP_N = 100


class SearchService:
    """Service for semantic search and active notebook listing.

    All queries are strictly scoped by `user_id` and restricted to active
    (`UserFileDO.is_active == "Y"`) `.note` files. When `embedding_model` is
    `None`, `search_chunks` returns an empty list while `list_notebooks`
    remains available.
    """

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        embedding_model: EmbeddingModel | None,
    ) -> None:
        """Initialize the search service.

        Args:
            session_manager: Async SQLAlchemy session manager for querying
                `UserFileDO` and `NotePageContentDO`.
            embedding_model: Optional configured embedding backend used to
                embed search queries. May be bound later during startup once
                AI capability platforms finish loading.
        """
        self.session_manager = session_manager
        self.embedding_model = embedding_model
        self._embedding_searcher = EmbeddingChunkSearcher()

    async def list_notebooks(
        self,
        user_id: int,
        name_filter: str | None = None,
        limit: int = 20,
    ) -> list[NotebookInfo]:
        """List active `.note` notebooks for a user ordered by most recently updated."""
        if limit <= 0:
            return []
        capped_limit = min(limit, _MAX_NOTEBOOK_LIMIT)
        async with self.session_manager.session() as session:
            stmt = (
                select(UserFileDO)
                .where(UserFileDO.user_id == user_id)
                .where(UserFileDO.is_active == "Y")
                .where(UserFileDO.is_folder == "N")
                .where(UserFileDO.file_name.ilike("%.note"))
            )
            if name_filter:
                stmt = stmt.where(
                    UserFileDO.file_name.icontains(name_filter, autoescape=True)
                )
            stmt = stmt.order_by(UserFileDO.update_time.desc()).limit(capped_limit)
            files = (await session.execute(stmt)).scalars().all()

        return [
            NotebookInfo(
                file_id=f.id,
                file_name=f.file_name,
                create_time=f.create_time,
                update_time=f.update_time,
            )
            for f in files
        ]

    async def search_chunks(
        self,
        user_id: int,
        query: str,
        top_n: int = 5,
        name_filter: str | None = None,
        date_after: str | None = None,
        date_before: str | None = None,
    ) -> list[SearchResult]:
        """Search active `.note` pages semantically similar to `query`.

        Args:
            user_id: Owner user ID performing the search.
            query: Natural-language search query string.
            top_n: Maximum number of ranked results to return (capped at 100).
            name_filter: Optional case-insensitive substring filter on notebook
                filenames.
            date_after: Optional ISO calendar date (`YYYY-MM-DD`). Keeps pages
                whose inferred date is on or after this date.
            date_before: Optional ISO calendar date (`YYYY-MM-DD`). Keeps pages
                whose inferred date is on or before this date.

        Returns:
            List of `SearchResult` sorted by descending cosine similarity.
        """
        if top_n <= 0 or not query or not query.strip():
            return []
        capped_top_n = min(top_n, _MAX_TOP_N)

        after_date: date | None = None
        before_date: date | None = None
        try:
            if date_after:
                after_date = date.fromisoformat(date_after)
            if date_before:
                before_date = date.fromisoformat(date_before)
        except ValueError as e:
            logger.warning(f"Invalid date filter format: {e}")
            return []

        if after_date and before_date and after_date > before_date:
            return []

        # Embed the query before opening a DB session so remote AI provider network
        # latency never holds an active SQLite connection.
        model = self.embedding_model
        query_unit = await self._embedding_searcher.embed_query(query, model)
        if model is None or query_unit is None:
            return []

        search_query = SearchQuery(
            user_id=user_id,
            raw_query=query,
            top_n=capped_top_n,
            name_filter=name_filter,
            after_date=after_date,
            before_date=before_date,
        )
        async with self.session_manager.session() as session:
            return await self._embedding_searcher.search(
                session, search_query, query_unit, model
            )


SEARCH_SERVICE_KEY: web.AppKey[SearchService] = web.AppKey("search_service")
"""Typed `aiohttp.web.AppKey` exposing `SearchService` to sibling components and routes."""
