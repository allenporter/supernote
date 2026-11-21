"""Hybrid keyword + semantic vector search and notebook transcript retrieval service.

`SearchService` orchestrates `KeywordChunkSearcher` (matching native Supernote
`NotePageMetadataDO` keywords and `NotePageContentDO` OCR transcripts) alongside
`EmbeddingChunkSearcher` (computing cosine similarity via `EmbeddingModel`), merging
results via `rank_and_merge_results` while supporting filename substring filters and
ISO 8601 date bounds (`infer_page_date`). Powers both the MCP tools in
`supernote.server.mcp.server` and the Web UI search endpoints in
`supernote.server.routes.extended`. See `supernote.guides.mcp`.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select

from supernote.server.ai.models.embedding import EmbeddingModel
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.chunk_search import (
    EmbeddingChunkSearcher,
    KeywordChunkSearcher,
    SearchQuery,
    SearchResult,
    normalize_keyword_query,
    rank_and_merge_results,
)
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_keywords_map,
    infer_page_date,
)

logger = logging.getLogger(__name__)

__all__ = ["NotebookInfo", "PageTranscript", "SearchResult", "SearchService"]


@dataclass
class NotebookInfo:
    """Summary metadata for an active `.note` file."""

    file_id: int
    """Numeric VFS ID of the notebook."""
    file_name: str
    """Filename of the notebook."""
    create_time: int
    """Creation timestamp in epoch milliseconds."""
    update_time: int
    """Last modification timestamp in epoch milliseconds."""


@dataclass
class PageTranscript:
    """Structured OCR transcript for a single notebook page."""

    page_index: int
    """0-based page index within the notebook."""
    page_id: str
    """Stable Supernote PAGEID string."""
    text: str | None = None
    """Extracted OCR transcript text for the page."""
    date: str | None = None
    """Inferred ISO 8601 date (`YYYY-MM-DD`) when encoded in `page_id`."""


class SearchService:
    """Service for hybrid keyword and semantic search across notebook content."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        embedding_model: EmbeddingModel | None,
    ) -> None:
        self.session_manager = session_manager
        self._keyword_searcher = KeywordChunkSearcher(session_manager)
        self._embedding_searcher = EmbeddingChunkSearcher(
            session_manager, embedding_model
        )

    @property
    def embedding_model(self) -> EmbeddingModel | None:
        """Configured embedding model used by the vector chunk searcher, if any."""
        return self._embedding_searcher.embedding_model

    @embedding_model.setter
    def embedding_model(self, model: EmbeddingModel | None) -> None:
        self._embedding_searcher.embedding_model = model

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
                stmt = stmt.where(
                    UserFileDO.file_name.icontains(name_filter, autoescape=True)
                )
            stmt = stmt.order_by(UserFileDO.update_time.desc()).limit(limit)
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
        """Search notebook pages using hybrid keyword + semantic vector retrieval."""
        if top_n <= 0 or not normalize_keyword_query(query):
            return []

        after_date: date | None = None
        before_date: date | None = None
        try:
            if date_after:
                after_date = datetime.strptime(date_after, "%Y-%m-%d").date()
            if date_before:
                before_date = datetime.strptime(date_before, "%Y-%m-%d").date()
        except ValueError as e:
            logger.error(f"Invalid date filter format: {e}")
            return []

        if after_date and before_date and after_date > before_date:
            return []

        search_query = SearchQuery(
            user_id=user_id,
            raw_query=query,
            name_filter=name_filter,
            after_date=after_date,
            before_date=before_date,
        )
        keyword_hits = await self._keyword_searcher.search(search_query)
        embedding_hits = await self._embedding_searcher.search(search_query)
        return rank_and_merge_results(keyword_hits, embedding_hits, top_n=top_n)

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
            file_do = (await session.execute(stmt)).scalar_one_or_none()
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

            pages = list((await session.execute(content_stmt)).scalars().all())

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
        """Retrieve the transcript for a notebook or a specific page range."""
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
        if page_index is not None:
            return pages[0].text_content

        async with self.session_manager.session() as session:
            keywords_map = await get_page_keywords_map(session, user_id, file_id)

        text_parts = []
        for p in pages:
            if not p.is_blank:
                metadata = format_page_metadata(
                    page_index=p.page_index,
                    page_id=p.page_id,
                    file_name=file_do.file_name,
                    notebook_create_time=file_do.create_time,
                    keywords=keywords_map.get(p.page_id),
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
