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
import time
from collections.abc import Sequence

from aiohttp import web
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError

from supernote.models.base import BooleanEnum
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTitleDO,
    NoteTitleTranscriptDO,
)
from supernote.server.db.models.summary import SummaryTranscriptDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    LocalEventBus,
    SummaryDeletedEvent,
    SummaryUpdatedEvent,
)
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_keywords_map,
    infer_page_date,
)

from .models import PageTranscript, SummaryTranscript

__all__ = [
    "TRANSCRIPT_SERVICE_KEY",
    "TranscriptService",
]

logger = logging.getLogger(__name__)


def _to_summary_transcript(row: SummaryTranscriptDO) -> SummaryTranscript:
    """Convert a `SummaryTranscriptDO` row into its pure domain dataclass."""
    return SummaryTranscript(
        summary_id=int(row.summary_id),
        handwrite_md5=row.handwrite_md5,
        text=row.text_content,
        model_id=row.model_id,
        create_time=int(row.create_time),
        update_time=int(row.update_time),
    )


class TranscriptService:
    """Retrieves and manages OCR transcripts for `.note` pages, title crops, and Digest annotations.

    All queries are strictly scoped by `user_id`. Notebook queries are restricted to
    active (`UserFileDO.is_active == "Y"`) files.
    """

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        event_bus: LocalEventBus | None = None,
    ) -> None:
        """Initialize the transcript service.

        Args:
            session_manager: Async SQLAlchemy session manager for querying
                `UserFileDO`, `NotePageContentDO`, `SummaryTranscriptDO`, and page keyword metadata.
            event_bus: Optional core `LocalEventBus` used to clean up summary
                transcripts when `SummaryDeletedEvent` is published.
        """
        self.session_manager = session_manager
        self._event_bus = event_bus
        if self._event_bus is not None:
            self._event_bus.subscribe(
                SummaryDeletedEvent, self._handle_summary_deleted, inline=True
            )
            self._event_bus.subscribe(
                SummaryUpdatedEvent, self._handle_summary_updated, inline=True
            )

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

    async def get_title_transcripts(
        self,
        user_id: int,
        file_id: int,
    ) -> dict[str, str]:
        """Retrieve transcribed title text keyed by `bitmap_md5` for an active notebook."""
        async with self.session_manager.session() as session:
            file_do = (
                await session.execute(
                    select(UserFileDO.id).where(
                        UserFileDO.id == file_id,
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                    )
                )
            ).scalar_one_or_none()
            if file_do is None:
                return {}

            try:
                rows = (
                    await session.execute(
                        select(
                            NoteTitleTranscriptDO.bitmap_md5,
                            NoteTitleTranscriptDO.text_content,
                        )
                        .join(
                            NoteTitleDO,
                            (NoteTitleDO.user_id == NoteTitleTranscriptDO.user_id)
                            & (NoteTitleDO.file_id == NoteTitleTranscriptDO.file_id)
                            & (
                                NoteTitleDO.bitmap_md5
                                == NoteTitleTranscriptDO.bitmap_md5
                            ),
                        )
                        .where(
                            NoteTitleTranscriptDO.user_id == user_id,
                            NoteTitleTranscriptDO.file_id == file_id,
                        )
                    )
                ).all()
            except OperationalError as err:
                # Preserve read compatibility with unmigrated legacy databases
                # opened before `d0e1f2a3b4c5` (see legacy DB integration tests).
                if "no such table" in str(err).lower():
                    return {}
                raise
        return {md5: text for md5, text in rows if text}

    async def get_summary_transcript(
        self,
        user_id: int,
        summary_id: int,
    ) -> SummaryTranscript | None:
        """Retrieve the stored handwriting OCR transcript for a single Digest summary."""
        async with self.session_manager.session() as session:
            row = await session.get(SummaryTranscriptDO, (user_id, summary_id))
        return _to_summary_transcript(row) if row is not None else None

    async def get_summary_transcripts(
        self,
        user_id: int,
        summary_ids: Sequence[int],
    ) -> dict[int, SummaryTranscript]:
        """Batch-retrieve stored handwriting OCR transcripts keyed by `summary_id`."""
        if not summary_ids:
            return {}
        async with self.session_manager.session() as session:
            try:
                rows = (
                    (
                        await session.execute(
                            select(SummaryTranscriptDO).where(
                                SummaryTranscriptDO.user_id == user_id,
                                SummaryTranscriptDO.summary_id.in_(summary_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            except OperationalError as err:
                # Preserve read compatibility with unmigrated legacy databases
                # opened before `e1f2a3b4c5d6` (see legacy DB integration tests).
                if "no such table" in str(err).lower():
                    return {}
                raise
        return {int(row.summary_id): _to_summary_transcript(row) for row in rows}

    async def is_summary_transcript_stale(
        self,
        user_id: int,
        summary_id: int,
        handwrite_md5: str,
    ) -> bool:
        """Return True if no transcript exists for `(user_id, summary_id)` or its `handwrite_md5` differs."""
        async with self.session_manager.session() as session:
            stored_md5 = (
                await session.execute(
                    select(SummaryTranscriptDO.handwrite_md5).where(
                        SummaryTranscriptDO.user_id == user_id,
                        SummaryTranscriptDO.summary_id == summary_id,
                    )
                )
            ).scalar_one_or_none()
        return stored_md5 != handwrite_md5

    async def upsert_summary_transcript(
        self,
        user_id: int,
        summary_id: int,
        handwrite_md5: str,
        text_content: str,
        model_id: str | None = None,
    ) -> SummaryTranscript:
        """Insert or update the OCR transcript for a Digest summary's handwritten annotation."""
        now_ms = int(time.time() * 1000)

        def _apply_update(target: SummaryTranscriptDO) -> None:
            target.handwrite_md5 = handwrite_md5
            target.text_content = text_content
            target.model_id = model_id
            target.update_time = now_ms

        async with self.session_manager.session() as session:
            row = await session.get(SummaryTranscriptDO, (user_id, summary_id))
            if row is not None:
                _apply_update(row)
                await session.commit()
                return _to_summary_transcript(row)

            row = SummaryTranscriptDO(
                user_id=user_id,
                summary_id=summary_id,
                handwrite_md5=handwrite_md5,
                text_content=text_content,
                model_id=model_id,
                create_time=now_ms,
                update_time=now_ms,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = await session.get(SummaryTranscriptDO, (user_id, summary_id))
                if row is None:
                    raise
                _apply_update(row)
                await session.commit()
            return _to_summary_transcript(row)

    async def delete_summary_transcript(
        self,
        user_id: int,
        summary_id: int,
    ) -> bool:
        """Delete the stored transcript for `(user_id, summary_id)` if present."""
        async with self.session_manager.session() as session:
            result = await session.execute(
                delete(SummaryTranscriptDO).where(
                    SummaryTranscriptDO.user_id == user_id,
                    SummaryTranscriptDO.summary_id == summary_id,
                )
            )
            await session.commit()
        return bool(getattr(result, "rowcount", 0))

    async def _handle_summary_deleted(self, event: SummaryDeletedEvent) -> None:
        """Remove stored handwriting transcript when a leaf summary is deleted."""
        if event.is_summary_group:
            return
        await self.delete_summary_transcript(
            user_id=event.user_id,
            summary_id=event.summary_id,
        )

    async def _handle_summary_updated(self, event: SummaryUpdatedEvent) -> None:
        """Remove stored handwriting transcript when a leaf summary clears its handwriting."""
        summary = event.summary
        if summary.id is None or summary.is_summary_group == BooleanEnum.YES:
            return
        if not summary.handwrite_inner_name or not summary.handwrite_md5:
            await self.delete_summary_transcript(
                user_id=event.user_id,
                summary_id=summary.id,
            )


TRANSCRIPT_SERVICE_KEY: web.AppKey[TranscriptService] = web.AppKey("transcript_service")
"""Typed `aiohttp.web.AppKey` exposing `TranscriptService` to sibling components and routes."""
