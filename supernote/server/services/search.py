import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.gemini import GeminiService

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    file_id: int
    file_name: str
    page_index: int
    page_id: str
    score: float
    text_preview: str


class SearchService:
    """Service for semantic search across notebook content."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        gemini_service: GeminiService,
        config: ServerConfig,
    ) -> None:
        self.session_manager = session_manager
        self.gemini_service = gemini_service
        self.config = config

    async def search_chunks(
        self,
        user_id: int,
        query: str,
        top_n: int = 5,
        name_filter: Optional[str] = None,
        date_after: Optional[str] = None,  # Currently a placeholder
        date_before: Optional[str] = None,  # Currently a placeholder
    ) -> List[SearchResult]:
        """
        Search for notebook chunks similar to the query.

        Args:
            user_id: The ID of the user performing the search.
            query: The search query string.
            top_n: Number of results to return.
            name_filter: Optional substring to filter notebook filenames.
            date_after: Placeholder for future date-based filtering.
            date_before: Placeholder for future date-based filtering.
        """
        if not self.gemini_service.is_configured:
            logger.warning("Search requested but Gemini is not configured")
            return []

        # 1. Embed Query
        model_id = self.config.gemini_embedding_model
        try:
            response = await self.gemini_service.embed_content(
                model=model_id,
                contents=query,
            )
            if not response.embeddings:
                logger.error("No embeddings returned for query")
                return []

            # Process the embedding values
            query_embedding = np.array(response.embeddings[0].values)
        except (ValueError, RuntimeError, TypeError) as e:
            logger.error(f"Failed to fetch or process query embedding: {e}")
            return []

        query_norm = np.linalg.norm(query_embedding)

        # 2. Fetch Candidates
        async with self.session_manager.session() as session:
            # Note: We dropped summary-based date whitelisting as it was inaccurate.
            # In the future, we will use notebook metadata to infer page dates.

            stmt = (
                select(NotePageContentDO, UserFileDO.file_name)
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(UserFileDO.user_id == user_id)
                .where(NotePageContentDO.embedding.isnot(None))
            )

            if name_filter:
                stmt = stmt.where(UserFileDO.file_name.ilike(f"%{name_filter}%"))

            result = await session.execute(stmt)
            candidates = result.all()

        if not candidates:
            return []

        # 3. Calculate Similarity
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

                # Cosine Similarity
                score = np.dot(query_embedding, candidate_embedding) / (
                    query_norm * np.linalg.norm(candidate_embedding)
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Failed to process embedding math for result {content_do.id}: {e}"
                )
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
                )
            )

        # 4. Rank and Limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]
