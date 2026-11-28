"""OCR transcription stage (`TaskType.SUMMARY_OCR`) for handwritten Digest annotations.

`SummaryOcrModule` runs under `ProcessorService` (`entity_type = TaskEntityType.SUMMARY`),
rendering a Digest summary's `.mark` handwriting blob to PNG page(s) via `ConversionService`,
transcribing each page with `OcrModel` using `format_ocr_prompt` (and folder vocabulary when
linked to a notebook), joining multi-page text, and persisting the result via
`TranscriptService.upsert_summary_transcript`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from supernote.models.base import TaskType
from supernote.models.summary import SummaryItem
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.components.conversion import ConversionService
from supernote.server.components.processor import ProcessorModule
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import FileNotFound
from supernote.server.services.blob import BlobStorage

from .service import TranscriptService
from .vocabulary import notebook_terms

__all__ = ["SummaryOcrModule"]

logger = logging.getLogger(__name__)


def _summary_ocr_file_name(summary: SummaryDO, summary_id: int) -> str:
    """Resolve a human-readable source filename for OCR prompt context."""
    if summary.source_path:
        name = Path(summary.source_path).name
        if name:
            return name
    if summary.name:
        return summary.name
    return f"summary_{summary_id}.mark"


def _to_conversion_summary_item(summary: SummaryDO) -> SummaryItem:
    """Build the minimal `SummaryItem` needed by `ConversionService` summary renderers."""
    return SummaryItem(
        id=int(summary.id),
        handwrite_inner_name=summary.handwrite_inner_name,
        handwrite_md5=summary.handwrite_md5,
    )


class SummaryOcrModule(ProcessorModule):
    """Processor module that transcribes handwritten Supernote Digest `.mark` annotations."""

    def __init__(
        self,
        *,
        blob_storage: BlobStorage,
        conversion_service: ConversionService,
        transcript_service: TranscriptService,
        ocr_model: OcrModel | None,
    ) -> None:
        self.blob_storage = blob_storage
        self.conversion_service = conversion_service
        self.transcript_service = transcript_service
        self.ocr_model = ocr_model

    @property
    def name(self) -> str:
        return "SummaryOcrModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.SUMMARY_OCR

    @property
    def enabled(self) -> bool:
        return self.ocr_model is not None

    @property
    def version(self) -> str | None:
        return self.ocr_model.model_id if self.ocr_model is not None else None

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        if not self.enabled:
            return False
        summary_id = file_id
        async with session_manager.session() as session:
            summary_do = await session.get(SummaryDO, (summary_id, user_id))
        if (
            summary_do is None
            or summary_do.is_deleted
            or summary_do.is_summary_group
            or not summary_do.handwrite_inner_name
            or not summary_do.handwrite_md5
        ):
            return False
        return await self.transcript_service.is_summary_transcript_stale(
            user_id=user_id,
            summary_id=summary_id,
            handwrite_md5=summary_do.handwrite_md5,
        )

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        if self.ocr_model is None:
            raise ValueError("OCR model not configured")
        raw_user_id = kwargs.get("user_id")
        if not isinstance(raw_user_id, int):
            raise ValueError("user_id is required for SummaryOcrModule")
        user_id = raw_user_id
        summary_id = file_id

        # Bounded loop handles the case where a newer handwriting revision is saved
        # while OCR for an earlier revision is in flight (which enqueue_entity deduplicates).
        for _ in range(3):
            async with session_manager.session() as session:
                summary_do = await session.get(SummaryDO, (summary_id, user_id))
                if (
                    summary_do is None
                    or summary_do.is_deleted
                    or summary_do.is_summary_group
                    or not summary_do.handwrite_inner_name
                    or not summary_do.handwrite_md5
                ):
                    return
                user = await session.get(UserDO, user_id)
                if user is None:
                    logger.warning(
                        "Skipping summary OCR for summary %s: user %s not found",
                        summary_id,
                        user_id,
                    )
                    return
                user_email = user.email
                handwrite_md5 = summary_do.handwrite_md5
                file_name = _summary_ocr_file_name(summary_do, summary_id)
                creation_time = summary_do.creation_time
                summary_item = _to_conversion_summary_item(summary_do)
                vocabulary = (
                    await notebook_terms(session, user_id, int(summary_do.file_id))
                    if summary_do.file_id is not None
                    else ()
                )

            page_numbers = await self.conversion_service.convert_summary_to_png(
                user_email, summary_item
            )
            page_texts: list[str] = []
            for page_no in page_numbers:
                converted = await self.conversion_service.get_summary_png_page(
                    user_email, summary_item, page_no
                )
                if converted is None:
                    raise FileNotFound(
                        f"Rendered PNG page {page_no} missing for summary {summary_id}"
                    )
                png_bytes = await self.blob_storage.get_bytes(
                    CACHE_BUCKET, converted.storage_key
                )
                page_metadata = PageMetadata(
                    file_name=file_name,
                    page_index=page_no,
                    page_id=f"summary_{summary_id}_page_{page_no}",
                    notebook_create_time=creation_time,
                )
                prompt = format_ocr_prompt(page_metadata, vocabulary=vocabulary)
                stripped = (
                    await self.ocr_model.extract_text(png_bytes, prompt)
                ).strip()
                if stripped:
                    page_texts.append(stripped)

            # Re-verify live SummaryDO still matches before persisting so concurrent
            # deletes or handwriting updates can never be overwritten with stale text.
            async with session_manager.session() as session:
                current = await session.get(SummaryDO, (summary_id, user_id))
                if (
                    current is None
                    or current.is_deleted
                    or not current.handwrite_inner_name
                    or not current.handwrite_md5
                ):
                    return
                if current.handwrite_md5 != handwrite_md5:
                    continue

            await self.transcript_service.upsert_summary_transcript(
                user_id=user_id,
                summary_id=summary_id,
                handwrite_md5=handwrite_md5,
                text_content="\n\n".join(page_texts),
                model_id=self.ocr_model.model_id,
            )
            logger.info(
                "Transcribed %d handwriting page(s) for summary %s (user %s, model=%s)",
                len(page_numbers),
                summary_id,
                user_id,
                self.ocr_model.model_id,
            )
            return
