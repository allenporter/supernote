import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.gemini import GeminiService
from supernote.server.utils.note_content import format_page_metadata, infer_page_date

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    file_id: int
    file_name: str
    page_index: int
    page_id: str
    score: float
    text_preview: str
    date: Optional[str] = None


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
        date_after: Optional[str] = None,
        date_before: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search for notebook chunks similar to the query.

        Args:
            user_id: The ID of the user performing the search.
            query: The search query string.
            top_n: Number of results to return.
            name_filter: Optional substring to filter notebook filenames.
            date_after: Optional ISO date string (YYYY-MM-DD). Filter results created after this date.
            date_before: Optional ISO date string (YYYY-MM-DD). Filter results created before this date.
        """
        if not self.gemini_service.is_configured:
            logger.warning("Search requested but Gemini is not configured")
            return []

        # Parse date filters
        after_dt: Optional[datetime] = None
        before_dt: Optional[datetime] = None
        try:
            if date_after:
                after_dt = datetime.strptime(date_after, "%Y-%m-%d")
            if date_before:
                before_dt = datetime.strptime(date_before, "%Y-%m-%d")
        except ValueError as e:
            logger.error(f"Invalid date filter format: {e}")
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
            # Metadata-based page filtering (Phase 2)
            # We use notebook metadata (PAGEID) to infer page dates and filter them.

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

                # Date Inference (Phase 2)
                page_date = infer_page_date(content_do.page_id)

                # Date Filtering (Inferred)
                # TODO: In the future we can replace this with LLM based date filtering
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

        # 4. Rank and Limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    async def get_transcript(
        self,
        user_id: int,
        file_id: int,
        page_index: Optional[int] = None,
        start_index: Optional[int] = None,
        end_index: Optional[int] = None,
    ) -> Optional[str]:
        """
        Retrieve the transcript for a notebook or a specific page range.

        Args:
            user_id: The ID of the user performing the retrieval.
            file_id: The ID of the notebook.
            page_index: Optional 0-based page index. If provided, returns raw text for this page.
            start_index: Optional 0-based start page index (inclusive).
            end_index: Optional 0-based end page index (inclusive).
        """
        async with self.session_manager.session() as session:
            # Verify ownership
            stmt = select(UserFileDO).where(
                UserFileDO.id == file_id, UserFileDO.user_id == user_id
            )
            result = await session.execute(stmt)
            file_do = result.scalar_one_or_none()
            if not file_do:
                logger.warning(
                    f"Unauthorized transcript request for file {file_id} by user {user_id}"
                )
                return None

            file_name = file_do.file_name

            # Fetch content
            content_stmt = select(NotePageContentDO).where(
                NotePageContentDO.file_id == file_id
            )
            if page_index is not None:
                content_stmt = content_stmt.where(
                    NotePageContentDO.page_index == page_index
                )
            else:
                if start_index is not None:
                    content_stmt = content_stmt.where(
                        NotePageContentDO.page_index >= start_index
                    )
                if end_index is not None:
                    content_stmt = content_stmt.where(
                        NotePageContentDO.page_index <= end_index
                    )
                content_stmt = content_stmt.order_by(NotePageContentDO.page_index)

            content_result = await session.execute(content_stmt)
            pages = content_result.scalars().all()

        if not pages:
            return None

        # Backward compatibility: raw text for single page index
        if page_index is not None:
            return pages[0].text_content

        # Aggregated transcript with metadata
        text_parts = []
        for p in pages:
            if p.text_content:
                metadata = format_page_metadata(
                    page_index=p.page_index,
                    page_id=p.page_id,
                    file_name=file_name,
                    notebook_create_time=file_do.create_time,
                    include_section_divider=True,
                )
                text_parts.append(f"{metadata}\n{p.text_content}")

        return "\n\n".join(text_parts)
