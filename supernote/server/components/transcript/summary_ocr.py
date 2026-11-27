"""Background OCR runner for handwritten Supernote Digest annotations (`SummaryOcrRunner`).

Subscribes to `SummaryCreatedEvent` and `SummaryUpdatedEvent` on the core
`LocalEventBus`. When a leaf summary carries a handwriting `.mark` blob
(`handwrite_inner_name` and `handwrite_md5`) whose stored transcript is missing
or stale (`TranscriptService.is_summary_transcript_stale`), the runner renders
the `.mark` blob to PNG page(s) via `ConversionService`, transcribes each page
with the configured `OcrModel` using `format_ocr_prompt`, joins multi-page text,
and persists the result via `TranscriptService.upsert_summary_transcript`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from supernote.models.base import BooleanEnum
from supernote.models.summary import SummaryItem
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.components.conversion import ConversionService
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    LocalEventBus,
    SummaryCreatedEvent,
    SummaryUpdatedEvent,
)
from supernote.server.exceptions import FileError, FileNotFound
from supernote.server.services.blob import BlobStorage

from .service import TranscriptService

__all__ = ["SummaryOcrRunner"]

logger = logging.getLogger(__name__)


def _summary_ocr_file_name(summary: SummaryItem, summary_id: int) -> str:
    """Resolve a human-readable source filename for OCR prompt context."""
    if summary.source_path:
        name = Path(summary.source_path).name
        if name:
            return name
    if summary.name:
        return summary.name
    return f"summary_{summary_id}.mark"


class SummaryOcrRunner:
    """Event-driven background OCR worker for handwritten Digest annotations."""

    def __init__(
        self,
        *,
        session_manager: DatabaseSessionManager,
        blob_storage: BlobStorage,
        conversion_service: ConversionService,
        transcript_service: TranscriptService,
        event_bus: LocalEventBus,
        ocr_model_getter: Callable[[], OcrModel | None],
    ) -> None:
        self._session_manager = session_manager
        self._blob_storage = blob_storage
        self._conversion_service = conversion_service
        self._transcript_service = transcript_service
        self._event_bus = event_bus
        self._get_ocr_model = ocr_model_getter
        self._started = False
        self._subscribed = False
        self._active_tasks: set[asyncio.Task[object]] = set()
        self._locks: dict[tuple[int, int], tuple[asyncio.Lock, int]] = {}

    async def start(self) -> None:
        """Start listening for summary create/update events (idempotent)."""
        if self._started:
            return
        self._started = True
        if not self._subscribed:
            self._subscribed = True
            self._event_bus.subscribe(
                SummaryCreatedEvent, self._handle_summary_event, inline=False
            )
            self._event_bus.subscribe(
                SummaryUpdatedEvent, self._handle_summary_event, inline=False
            )

    async def stop(self) -> None:
        """Stop accepting new work and cancel/drain any in-flight OCR tasks (idempotent)."""
        self._started = False
        tasks = list(self._active_tasks)
        self._active_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        """Wait for all currently active summary OCR tasks to complete."""
        while self._active_tasks:
            await asyncio.gather(*tuple(self._active_tasks), return_exceptions=True)

    @asynccontextmanager
    async def _summary_lock(self, key: tuple[int, int]) -> AsyncGenerator[None]:
        """Serialize concurrent OCR runs targeting the same `(user_id, summary_id)`."""
        lock, count = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, count + 1)
        try:
            async with lock:
                yield
        finally:
            cur_lock, cur_count = self._locks[key]
            if cur_count <= 1:
                self._locks.pop(key, None)
            else:
                self._locks[key] = (cur_lock, cur_count - 1)

    async def _handle_summary_event(
        self, event: SummaryCreatedEvent | SummaryUpdatedEvent
    ) -> None:
        """Background event handler for `SummaryCreatedEvent` and `SummaryUpdatedEvent`."""
        if not self._started:
            return
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks.add(task)
        try:
            await self.process_summary_event(event)
        except asyncio.CancelledError:
            raise
        except (FileNotFound, FileError) as err:
            logger.warning(
                "Skipping summary handwriting OCR for summary %s (user %s): %s",
                event.summary.id,
                event.user_id,
                err,
            )
        except Exception:
            logger.exception(
                "Failed to transcribe handwriting for summary %s (user %s)",
                event.summary.id,
                event.user_id,
            )
        finally:
            if task is not None:
                self._active_tasks.discard(task)

    async def process_summary_event(
        self, event: SummaryCreatedEvent | SummaryUpdatedEvent
    ) -> bool:
        """Transcribe a summary's handwriting if present, stale, and OCR is configured.

        Returns:
            True if a transcript was newly generated and persisted, False if skipped.
        """
        summary = event.summary
        if summary.id is None or summary.is_summary_group == BooleanEnum.YES:
            return False
        if not summary.handwrite_inner_name or not summary.handwrite_md5:
            return False
        if self._get_ocr_model() is None:
            return False

        user_id = event.user_id
        summary_id = int(summary.id)
        handwrite_md5 = summary.handwrite_md5

        async with self._summary_lock((user_id, summary_id)):
            if not self._started:
                return False
            ocr_model = self._get_ocr_model()
            if ocr_model is None:
                return False

            is_stale = await self._transcript_service.is_summary_transcript_stale(
                user_id=user_id,
                summary_id=summary_id,
                handwrite_md5=handwrite_md5,
            )
            if not is_stale:
                return False

            async with self._session_manager.session() as session:
                user = await session.get(UserDO, user_id)
            if user is None:
                logger.warning(
                    "Skipping summary OCR for summary %s: user %s not found",
                    summary_id,
                    user_id,
                )
                return False

            page_numbers = await self._conversion_service.convert_summary_to_png(
                user.email, summary
            )
            file_name = _summary_ocr_file_name(summary, summary_id)
            page_texts: list[str] = []
            loaded_pages = 0
            for page_no in page_numbers:
                converted = await self._conversion_service.get_summary_png_page(
                    user.email, summary, page_no
                )
                if converted is None:
                    logger.warning(
                        "Rendered PNG page %s missing for summary %s (user %s)",
                        page_no,
                        summary_id,
                        user_id,
                    )
                    continue
                png_bytes = await self._blob_storage.get_bytes(
                    CACHE_BUCKET, converted.storage_key
                )
                loaded_pages += 1
                page_metadata = PageMetadata(
                    file_name=file_name,
                    page_index=page_no,
                    page_id=f"summary_{summary_id}_page_{page_no}",
                    notebook_create_time=summary.creation_time,
                )
                prompt = format_ocr_prompt(page_metadata)
                raw_text = await ocr_model.extract_text(png_bytes, prompt)
                stripped = raw_text.strip()
                if stripped:
                    page_texts.append(stripped)

            if page_numbers and loaded_pages == 0:
                return False

            if not self._started:
                return False

            text_content = "\n\n".join(page_texts)
            await self._transcript_service.upsert_summary_transcript(
                user_id=user_id,
                summary_id=summary_id,
                handwrite_md5=handwrite_md5,
                text_content=text_content,
                model_id=ocr_model.model_id,
            )
            logger.info(
                "Transcribed %d handwriting page(s) for summary %s (user %s, model=%s)",
                loaded_pages,
                summary_id,
                user_id,
                ocr_model.model_id,
            )
            return True
