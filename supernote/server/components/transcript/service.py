"""Notebook OCR transcript retrieval service (`TranscriptService`).

Reads per-page OCR transcripts from
`supernote.server.db.models.note_processing.NotePageContentDO` joined with
active `supernote.server.db.models.file.UserFileDO` ownership checks,
enriching aggregated transcripts with verified native page keywords
(`get_page_keywords_map`) and page metadata (`format_page_metadata`).

Has zero dependency on AI embedding backends so transcript retrieval remains
available regardless of search or embedding configuration.

### Internal Component Access

Other server components or plugins declaring ``dependencies = ("transcript",)``
retrieve the shared service instance via `core.app[TRANSCRIPT_SERVICE_KEY]`.
"""

from __future__ import annotations

import logging

from aiohttp import web
from sqlalchemy import select

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_keywords_map,
    infer_page_date,
)

from .models import PageTranscript

__all__ = [
    "TRANSCRIPT_SERVICE_KEY",
    "TranscriptService",
]

logger = logging.getLogger(__name__)


class TranscriptService:
    """Retrieves formatted and structured per-page OCR transcripts for `.note` files.

    All queries are strictly scoped by `user_id` and restricted to active
    (`UserFileDO.is_active == "Y"`) files.
    """

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        """Initialize the transcript service.

        Args:
            session_manager: Async SQLAlchemy session manager for querying
                `UserFileDO`, `NotePageContentDO`, and page keyword metadata.
        """
        self.session_manager = session_manager

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
        """Retrieve a formatted transcript for a notebook or a specific page range.

        Args:
            user_id: Owner user ID performing the retrieval.
            file_id: VFS file ID of the notebook.
            page_index: Optional 0-based page index; when set, returns raw text
                for that single page.
            start_index: Optional 0-based start page index (inclusive).
            end_index: Optional 0-based end page index (inclusive).

        Returns:
            Formatted transcript string with per-page metadata headers and
            verified keywords, or `None` if the notebook is not accessible or
            has no transcribed pages.
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


TRANSCRIPT_SERVICE_KEY: web.AppKey[TranscriptService] = web.AppKey("transcript_service")
"""Typed `aiohttp.web.AppKey` exposing `TranscriptService` to sibling components and routes."""
