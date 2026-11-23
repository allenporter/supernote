"""Semantic vector search and notebook transcript retrieval service.

`SearchService` embeds natural-language search queries via
`supernote.server.ai.models.embedding.EmbeddingModel`
(`EmbeddingTaskType.RETRIEVAL_QUERY`) and computes cosine similarity against
page embeddings stored in `supernote.server.db.models.note_processing.NotePageContentDO`,
supporting filename substring filters and ISO 8601 date bounds
(`infer_page_date`).

### Internal Component Access

Other server components or plugins declaring ``dependencies = ("search",)``
retrieve the shared service instance via `core.app[SEARCH_SERVICE_KEY]`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import numpy as np
from aiohttp import web
from sqlalchemy import select

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.note_content import infer_page_date

from .models import NotebookInfo, SearchResult

__all__ = [
    "SEARCH_SERVICE_KEY",
    "SearchService",
]

logger = logging.getLogger(__name__)


class SearchService:
    """Service for semantic search, notebook listing, and transcript retrieval.

    All queries are strictly scoped by `user_id` and restricted to active
    (`UserFileDO.is_active == "Y"`) files. When `embedding_model` is `None`,
    `search_chunks` returns an empty list while `list_notebooks` remains
    available.
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

    async def list_notebooks(
        self,
        user_id: int,
        name_filter: str | None = None,
        limit: int = 20,
    ) -> list[NotebookInfo]:
        """List active `.note` notebooks for a user ordered by most recently updated."""
        async with self.session_manager.session() as session:
            stmt = (
                select(UserFileDO)
                .where(UserFileDO.user_id == user_id)
                .where(UserFileDO.is_active == "Y")
                .where(UserFileDO.is_folder == "N")
                .where(UserFileDO.file_name.ilike("%.note"))
            )
            if name_filter:
                stmt = stmt.where(UserFileDO.file_name.ilike(f"%{name_filter}%"))
            stmt = stmt.order_by(UserFileDO.update_time.desc()).limit(limit)
            result = await session.execute(stmt)
            files = result.scalars().all()

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
        """Search for notebook chunks semantically similar to `query`.

        Args:
            user_id: Owner user ID performing the search.
            query: Natural-language search query string.
            top_n: Maximum number of ranked results to return.
            name_filter: Optional case-insensitive substring filter on notebook
                filenames.
            date_after: Optional ISO date string (`YYYY-MM-DD`). Keeps pages
                whose inferred date is on or after this date.
            date_before: Optional ISO date string (`YYYY-MM-DD`). Keeps pages
                whose inferred date is on or before this date.

        Returns:
            List of `SearchResult` sorted by descending cosine similarity.
        """
        if self.embedding_model is None:
            logger.warning("Search requested but embedding model is not configured")
            return []

        after_dt: datetime | None = None
        before_dt: datetime | None = None
        try:
            if date_after:
                after_dt = datetime.strptime(date_after, "%Y-%m-%d")
            if date_before:
                before_dt = datetime.strptime(date_before, "%Y-%m-%d")
        except ValueError as e:
            logger.error(f"Invalid date filter format: {e}")
            return []

        try:
            embedding_values = await self.embedding_model.embed(
                query, task_type=EmbeddingTaskType.RETRIEVAL_QUERY
            )
            query_embedding = np.array(embedding_values)
        except (AIError, ValueError, TypeError) as e:
            logger.error(f"Failed to fetch or process query embedding: {e}")
            return []

        query_norm = np.linalg.norm(query_embedding)

        async with self.session_manager.session() as session:
            stmt = (
                select(NotePageContentDO, UserFileDO.file_name)
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(UserFileDO.user_id == user_id)
                .where(UserFileDO.is_active == "Y")
                .where(NotePageContentDO.embedding.isnot(None))
                .where(
                    NotePageContentDO.embedding_model == self.embedding_model.model_id
                )
            )

            if name_filter:
                stmt = stmt.where(UserFileDO.file_name.ilike(f"%{name_filter}%"))

            result = await session.execute(stmt)
            candidates = result.all()

        if not candidates:
            return []

        results = []
        for content_do, file_name in candidates:
            if not content_do.embedding:
                continue

            try:
                embedding_list = json.loads(content_do.embedding)
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to decode embedding JSON for result {content_do.id}: {e}"
                )
                continue

            try:
                candidate_embedding = np.array(embedding_list)

                score = np.dot(query_embedding, candidate_embedding) / (
                    query_norm * np.linalg.norm(candidate_embedding)
                )

                page_date = infer_page_date(content_do.page_id)

                if after_dt and (not page_date or page_date < after_dt):
                    continue
                if before_dt and (not page_date or page_date > before_dt):
                    continue

                results.append(
                    SearchResult(
                        file_id=content_do.file_id,
                        file_name=file_name,
                        page_index=content_do.page_index,
                        page_id=content_do.page_id,
                        score=float(score),
                        text_preview=content_do.text_content[:200]
                        if content_do.text_content
                        else "",
                        date=page_date.strftime("%Y-%m-%d") if page_date else None,
                    )
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Failed to process embedding math for result {content_do.id}: {e}"
                )
                continue

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]


SEARCH_SERVICE_KEY: web.AppKey[SearchService] = web.AppKey("search_service")
"""Typed `aiohttp.web.AppKey` exposing `SearchService` to sibling components and routes."""
