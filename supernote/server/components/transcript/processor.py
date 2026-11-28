"""OCR transcription stage (`TaskType.OCR_EXTRACTION`) for `.note` pages and title crops.

`OcrModule` loads cached page PNGs from `CACHE_BUCKET`, formats a notebook-aware
transcription prompt via `supernote.server.ai.prompts.format_ocr_prompt`, and saves
the Markdown transcript to `NotePageContentDO.text_content`. For pages with native
Supernote headings (`NoteTitleDO`), it also transcribes uncached `<TITLEBITMAP>` crops
into `NoteTitleTranscriptDO` keyed by `(user_id, file_id, bitmap_md5)` using
`format_title_ocr_prompt`. See `supernote.guides.mcp`.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import (
    PageMetadata,
    format_image_ocr_prompt,
    format_ocr_prompt,
    format_title_ocr_prompt,
)
from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.conversion import CONVERSION_SERVICE_KEY
from supernote.server.components.note_metadata import (
    NOTE_METADATA_SERVICE_KEY,
    NoteMetadataService,
)
from supernote.server.components.processor import (
    ProcessorModule,
    ProcessorRegistrar,
    TaskScope,
)
from supernote.server.constants import CACHE_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageMetadataDO,
    NoteTitleDO,
    NoteTitleTranscriptDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NotePageTranscribedEvent
from supernote.server.services.file import FileService
from supernote.server.utils.image import is_image_filename
from supernote.server.utils.note_content import get_page_content_by_id
from supernote.server.utils.paths import get_page_png_path
from supernote.server.utils.tasks import get_task

from .service import TRANSCRIPT_SERVICE_KEY
from .summary_ocr import SummaryOcrModule
from .vocabulary import notebook_terms

logger = logging.getLogger(__name__)


async def _get_verified_page_metadata(
    session: AsyncSession,
    user_id: int,
    file_id: int,
    page_id: str,
    content_hash: str | None,
) -> NotePageMetadataDO | None:
    """Return page metadata only when its revision hash matches the page content row."""
    if not content_hash:
        return None
    page_meta = (
        await session.execute(
            select(NotePageMetadataDO).where(
                NotePageMetadataDO.user_id == user_id,
                NotePageMetadataDO.file_id == file_id,
                NotePageMetadataDO.page_id == page_id,
            )
        )
    ).scalar_one_or_none()
    if page_meta is None or page_meta.content_hash != content_hash:
        return None
    return page_meta


async def _has_untranscribed_titles(
    session: AsyncSession,
    user_id: int,
    file_id: int,
    page_index: int,
) -> bool:
    """Return True if the page has any `<TITLEBITMAP>` not yet in `f_note_title_transcript`."""
    page_md5s = {
        md5
        for md5 in (
            await session.execute(
                select(NoteTitleDO.bitmap_md5).where(
                    NoteTitleDO.user_id == user_id,
                    NoteTitleDO.file_id == file_id,
                    NoteTitleDO.page_index == page_index,
                    NoteTitleDO.bitmap_md5.is_not(None),
                )
            )
        ).scalars()
        if md5
    }
    if not page_md5s:
        return False
    existing_md5s = set(
        (
            await session.execute(
                select(NoteTitleTranscriptDO.bitmap_md5).where(
                    NoteTitleTranscriptDO.user_id == user_id,
                    NoteTitleTranscriptDO.file_id == file_id,
                    NoteTitleTranscriptDO.bitmap_md5.in_(page_md5s),
                )
            )
        ).scalars()
    )
    return bool(page_md5s - existing_md5s)


class OcrModule(ProcessorModule):
    """Module responsible for extracting text from note pages and title crops using an `OcrModel`."""

    def __init__(
        self,
        file_service: FileService,
        ocr_model: OcrModel | None,
        note_metadata_service: NoteMetadataService | None = None,
    ) -> None:
        self.file_service = file_service
        self.ocr_model = ocr_model
        self.note_metadata_service = note_metadata_service

    @property
    def name(self) -> str:
        return "OcrModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.OCR_EXTRACTION

    @property
    def scope(self) -> TaskScope:
        return TaskScope.PAGE

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return (TaskType.PNG_CONVERSION, TaskType.NOTE_METADATA)

    @property
    def enabled(self) -> bool:
        return self.ocr_model is not None

    @property
    def version(self) -> str:
        """Module schema version recorded in `SystemTaskDO.data` (`v2` adds title OCR)."""
        return "v2"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        if page_index is None or not page_id or not self.enabled:
            return False

        key = self.get_task_key(page_index, page_id)
        task = await get_task(
            session_manager,
            user_id,
            file_id,
            self.task_type,
            key,
            entity_type=self.entity_type,
        )
        task_completed = task is not None and task.status == ProcessingStatus.COMPLETED
        task_current = task_completed and task.data == self.version

        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            if content is None:
                logger.warning(
                    f"Page content prerequisite not met for OCR of {file_id} page {page_id}"
                )
                return False
            file_do = await session.get(UserFileDO, file_id)
            if file_do is None or file_do.user_id != user_id:
                return False
            if task_current:
                if self.note_metadata_service is None:
                    return False
                return await _has_untranscribed_titles(
                    session, user_id, file_id, int(content.page_index)
                )
            # Legacy completed page being upgraded to v2: process() takes the
            # title-only fast path without needing the cached page PNG.
            if task_completed and content.text_content is not None:
                return True
            page_meta = await _get_verified_page_metadata(
                session, user_id, file_id, page_id, content.content_hash
            )
            if page_meta is not None and not page_meta.has_drawables:
                return True

        # Check if PNG exists (Prerequisite)
        png_path = get_page_png_path(file_id, page_id)
        if not await self.file_service.blob_storage.exists(CACHE_BUCKET, png_path):
            logger.warning(
                f"PNG prerequisite not met for OCR of {file_id} page {page_id}"
            )
            return False

        return True

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete persisted title transcripts for a purged file."""
        async with session_manager.session() as session:
            await session.execute(
                delete(NoteTitleTranscriptDO).where(
                    NoteTitleTranscriptDO.user_id == user_id,
                    NoteTitleTranscriptDO.file_id == file_id,
                )
            )
            await session.commit()

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        if page_id is None:
            logger.error(f"Page ID required for OCR processing of file {file_id}")
            return

        if self.ocr_model is None:
            raise ValueError("OCR model not configured")

        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            file_do = await session.get(UserFileDO, file_id)
            if content is None or file_do is None:
                logger.warning(
                    f"Missing page or file row for OCR of {file_id} page {page_id}"
                )
                return

            user_id = file_do.user_id
            file_name = file_do.file_name
            saved_page_index = int(content.page_index)
            key = self.get_task_key(page_index, page_id)
            task = await get_task(
                session_manager,
                user_id,
                file_id,
                self.task_type,
                key,
                entity_type=self.entity_type,
            )
            # Fast path when a page is already completed and transcribed (e.g.
            # version upgrade backfill or footer-only title edit): skip fetching
            # the cached page PNG and avoid a redundant full-page LLM call; only
            # OCR any missing title crops. Explicit reprocessing clears the task
            # row so `task` is None and full-page OCR still runs.
            title_only = (
                task is not None
                and task.status == ProcessingStatus.COMPLETED
                and content.text_content is not None
            )
            page_meta = (
                None
                if title_only
                else await _get_verified_page_metadata(
                    session, user_id, file_id, page_id, content.content_hash
                )
            )
            if not title_only and page_meta is not None and not page_meta.has_drawables:
                previous_text = (
                    content.text_content
                    if content.text_content is not None
                    else content.previous_text
                ) or None
                content.text_content = ""
                content.previous_text = None
                await session.commit()
                logger.info(
                    f"Skipping OCR LLM call for blank page {page_id} of file {file_id}"
                )
                await self._publish_page_transcribed(
                    user_id=user_id,
                    file_id=file_id,
                    page_id=page_id,
                    page_index=saved_page_index,
                    text_content="",
                    previous_text=previous_text,
                )
                await self._transcribe_page_titles(
                    session_manager,
                    user_id=user_id,
                    file_id=file_id,
                    page_index=saved_page_index,
                    file_name=file_do.file_name,
                )
                return

            if not title_only:
                page_metadata = PageMetadata(
                    file_name=file_name,
                    page_index=page_index
                    if page_index is not None
                    else saved_page_index,
                    page_id=page_id,
                    notebook_create_time=file_do.create_time,
                )
                if page_meta is not None:
                    page_metadata.page_style = page_meta.page_style
                    page_metadata.keywords = page_meta.keyword_texts
                if is_image_filename(file_name):
                    prompt = format_image_ocr_prompt(page_metadata)
                else:
                    vocabulary = await notebook_terms(session, user_id, file_id)
                    prompt = format_ocr_prompt(page_metadata, vocabulary=vocabulary)

        if title_only:
            await self._transcribe_page_titles(
                session_manager,
                user_id=user_id,
                file_id=file_id,
                page_index=saved_page_index,
                file_name=file_name,
            )
            logger.info(f"Completed title-only OCR for file {file_id} page {page_id}")
            return

        png_path = get_page_png_path(file_id, page_id)
        png_data = await self.file_service.blob_storage.get_bytes(
            CACHE_BUCKET, png_path
        )
        text_content = await self.ocr_model.extract_text(png_data, prompt)

        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            if content is None:
                logger.warning(
                    f"NotePageContentDO missing for {file_id} page {page_id} during OCR"
                )
                return
            previous_text = (
                content.text_content
                if content.text_content is not None
                else content.previous_text
            ) or None
            content.text_content = text_content
            content.previous_text = None
            saved_page_index = int(content.page_index)
            await session.commit()

        await self._publish_page_transcribed(
            user_id=user_id,
            file_id=file_id,
            page_id=page_id,
            page_index=saved_page_index,
            text_content=text_content,
            previous_text=previous_text,
        )
        await self._transcribe_page_titles(
            session_manager,
            user_id=user_id,
            file_id=file_id,
            page_index=saved_page_index,
            file_name=file_do.file_name,
        )

        logger.info(f"Completed OCR for file {file_id} page {page_id}")

    async def _transcribe_page_titles(
        self,
        session_manager: DatabaseSessionManager,
        *,
        user_id: int,
        file_id: int,
        page_index: int,
        file_name: str | None,
    ) -> None:
        """Transcribe any uncached `<TITLEBITMAP>` crops on `page_index` and prune stale transcripts."""
        if self.note_metadata_service is None or self.ocr_model is None:
            return

        async with session_manager.session() as session:
            all_titles = list(
                (
                    await session.execute(
                        select(NoteTitleDO.page_index, NoteTitleDO.bitmap_md5)
                        .where(
                            NoteTitleDO.user_id == user_id,
                            NoteTitleDO.file_id == file_id,
                            NoteTitleDO.bitmap_md5.is_not(None),
                        )
                        .order_by(NoteTitleDO.title_index)
                    )
                ).all()
            )
            active_md5s = {md5 for _, md5 in all_titles if md5}
            page_md5s = list(
                dict.fromkeys(
                    md5 for p_idx, md5 in all_titles if p_idx == page_index and md5
                )
            )
            existing_md5s = set(
                (
                    await session.execute(
                        select(NoteTitleTranscriptDO.bitmap_md5).where(
                            NoteTitleTranscriptDO.user_id == user_id,
                            NoteTitleTranscriptDO.file_id == file_id,
                        )
                    )
                ).scalars()
            )
            stale_md5s = existing_md5s - active_md5s
            if stale_md5s:
                await session.execute(
                    delete(NoteTitleTranscriptDO).where(
                        NoteTitleTranscriptDO.user_id == user_id,
                        NoteTitleTranscriptDO.file_id == file_id,
                        NoteTitleTranscriptDO.bitmap_md5.in_(stale_md5s),
                    )
                )
                await session.commit()

        missing_md5s = [md5 for md5 in page_md5s if md5 not in existing_md5s]
        if not missing_md5s:
            return

        title_prompt = format_title_ocr_prompt(file_name=file_name)
        for bitmap_md5 in missing_md5s:
            png_key = await self.note_metadata_service.get_title_png_key(
                user_id=user_id, file_id=file_id, bitmap_md5=bitmap_md5
            )
            if png_key is None:
                logger.warning(
                    f"Title crop unavailable for file {file_id} bitmap {bitmap_md5}; recording empty transcript"
                )
                normalized_text = ""
            else:
                png_bytes = await self.file_service.blob_storage.get_bytes(
                    CACHE_BUCKET, png_key
                )
                raw_text = await self.ocr_model.extract_text(png_bytes, title_prompt)
                normalized_text = " ".join(raw_text.split())
            await self._upsert_title_transcript(
                session_manager,
                user_id=user_id,
                file_id=file_id,
                bitmap_md5=bitmap_md5,
                text_content=normalized_text,
            )

    async def _upsert_title_transcript(
        self,
        session_manager: DatabaseSessionManager,
        *,
        user_id: int,
        file_id: int,
        bitmap_md5: str,
        text_content: str,
    ) -> None:
        """Persist a title transcript safely even if two pages race on the same `bitmap_md5`."""
        async with session_manager.session() as session:
            existing_row = await session.get(
                NoteTitleTranscriptDO, (user_id, file_id, bitmap_md5)
            )
            if existing_row is not None:
                existing_row.text_content = text_content
                await session.commit()
                return
            session.add(
                NoteTitleTranscriptDO(
                    user_id=user_id,
                    file_id=file_id,
                    bitmap_md5=bitmap_md5,
                    text_content=text_content,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing_row = await session.get(
                    NoteTitleTranscriptDO, (user_id, file_id, bitmap_md5)
                )
                if existing_row is not None:
                    existing_row.text_content = text_content
                    await session.commit()

    async def _publish_page_transcribed(
        self,
        *,
        user_id: int,
        file_id: int,
        page_id: str,
        page_index: int,
        text_content: str,
        previous_text: str | None,
    ) -> None:
        if not self.file_service.event_bus or text_content == (previous_text or ""):
            return
        file_path = await self.file_service.get_full_path_by_node(user_id, file_id)
        await self.file_service.event_bus.publish(
            NotePageTranscribedEvent(
                user_id=user_id,
                file_id=file_id,
                file_path=file_path,
                page_id=page_id,
                page_index=page_index,
                text_content=text_content,
                previous_text=previous_text,
            )
        )


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register `OcrModule` and `SummaryOcrModule` with the `"processor"` platform."""
    ocr_model = core.app.get(OCR_MODEL_KEY)
    registrar.register_module(
        OcrModule(
            file_service=core.file_service,
            ocr_model=ocr_model,
            note_metadata_service=core.app.get(NOTE_METADATA_SERVICE_KEY),
        )
    )
    registrar.register_module(
        SummaryOcrModule(
            blob_storage=core.blob_storage,
            conversion_service=core.app[CONVERSION_SERVICE_KEY],
            transcript_service=core.app[TRANSCRIPT_SERVICE_KEY],
            ocr_model=ocr_model,
        )
    )
