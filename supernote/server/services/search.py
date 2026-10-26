import json
import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy import select

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
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
    date: str | None = None


@dataclass
class NotebookInfo:
    file_id: int
    file_name: str
    create_time: int
    update_time: int


@dataclass
class PageTranscript:
    page_index: int
    page_id: str
    text: str | None = None
    date: str | None = None


class SearchService:
    """Service for semantic search across notebook content."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        embedding_model: EmbeddingModel | None,
    ) -> None:
        self.session_manager = session_manager
        self.embedding_model = embedding_model

    async def list_notebooks(
        self,
        user_id: int,
        name_filter: str | None = None,
        limit: int = 20,
    ) -> list[NotebookInfo]:
        """List active .note notebooks for a user ordered by most recently updated."""
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
        if self.embedding_model is None:
            logger.warning("Search requested but embedding model is not configured")
            return []

        # Parse date filters
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
            # Metadata-based page filtering (Phase 2)
            # We use notebook metadata (PAGEID) to infer page dates and filter them.

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

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    async def _fetch_notebook_pages(
        self,
        user_id: int,
        file_id: int,
        page_index: int | None = None,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> tuple[UserFileDO, list[NotePageContentDO]] | None:
        async with self.session_manager.session() as session:
            stmt = select(UserFileDO).where(
                UserFileDO.id == file_id,
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
            )
            result = await session.execute(stmt)
            file_do = result.scalar_one_or_none()
            if not file_do:
                logger.warning(
                    f"Unauthorized transcript request for file {file_id} by user {user_id}"
                )
                return None

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
            pages = list(content_result.scalars().all())

        if not pages or not any(p.text_content for p in pages):
            return None

        return file_do, pages

    async def get_transcript(
        self,
        user_id: int,
        file_id: int,
        page_index: int | None = None,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> str | None:
        """
        Retrieve the transcript for a notebook or a specific page range.

        Args:
            user_id: The ID of the user performing the retrieval.
            file_id: The ID of the notebook.
            page_index: Optional 0-based page index. If provided, returns raw text for this page.
            start_index: Optional 0-based start page index (inclusive).
            end_index: Optional 0-based end page index (inclusive).
        """
        fetched = await self._fetch_notebook_pages(
            user_id=user_id,
            file_id=file_id,
            page_index=page_index,
            start_index=start_index,
            end_index=end_index,
        )
        if fetched is None:
            return None

        file_do, pages = fetched

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
                    file_name=file_do.file_name,
                    notebook_create_time=file_do.create_time,
                    include_section_divider=True,
                )
                text_parts.append(f"{metadata}\n{p.text_content}")

        return "\n\n".join(text_parts)

    async def get_page_transcripts(
        self,
        user_id: int,
        file_id: int,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> list[PageTranscript]:
        """Retrieve structured per-page transcripts for a notebook or page range."""
        fetched = await self._fetch_notebook_pages(
            user_id=user_id,
            file_id=file_id,
            start_index=start_index,
            end_index=end_index,
        )
        if fetched is None:
            return []

        _, pages = fetched
        results: list[PageTranscript] = []
        for p in pages:
            page_date = infer_page_date(p.page_id)
            results.append(
                PageTranscript(
                    page_index=p.page_index,
                    page_id=p.page_id,
                    text=p.text_content,
                    date=page_date.strftime("%Y-%m-%d") if page_date else None,
                )
            )
        return results
