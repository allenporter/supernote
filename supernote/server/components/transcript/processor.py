"""Stage 3 of the `.note` processing pipeline: vision-model OCR extraction (`TaskType.OCR_EXTRACTION`).

`OcrModule` loads the cached page PNG from `CACHE_BUCKET`, formats a notebook-aware
transcription prompt via `supernote.server.ai.prompts.format_ocr_prompt` (routing custom
prompts through `supernote.server.utils.prompt_loader.PROMPT_LOADER`), and invokes
`supernote.server.ai.models.ocr.OcrModel.extract_text`. The resulting Markdown transcript
is saved to `NotePageContentDO.text_content`. See `supernote.guides.mcp`.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import TaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import (
    PageMetadata,
    format_image_ocr_prompt,
    format_ocr_prompt,
    format_title_ocr_prompt,
)
from supernote.server.components.ai import OCR_MODEL_KEY
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

        page_ocr_needed = await super().run_if_needed(
            file_id, session_manager, page_index, page_id, user_id=user_id
        )

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
            if not page_ocr_needed:
                if self.note_metadata_service is None:
                    return False
                return await _has_untranscribed_titles(
                    session, user_id, file_id, int(content.page_index)
                )
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
            saved_page_index = int(content.page_index)
            page_meta = await _get_verified_page_metadata(
                session, user_id, file_id, page_id, content.content_hash
            )
            if page_meta is not None and not page_meta.has_drawables:
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

            page_metadata = PageMetadata(
                file_name=file_do.file_name,
                page_index=page_index if page_index is not None else saved_page_index,
                page_id=page_id,
                notebook_create_time=file_do.create_time,
            )
            if page_meta is not None:
                page_metadata.page_style = page_meta.page_style
                page_metadata.keywords = page_meta.keyword_texts
            prompt = (
                format_image_ocr_prompt(page_metadata)
                if is_image_filename(file_do.file_name)
                else format_ocr_prompt(page_metadata)
            )

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
                    f"Skipping title OCR for file {file_id} bitmap {bitmap_md5}: crop unavailable"
                )
                continue
            png_bytes = await self.file_service.blob_storage.get_bytes(
                CACHE_BUCKET, png_key
            )
            raw_text = await self.ocr_model.extract_text(png_bytes, title_prompt)
            normalized_text = " ".join(raw_text.split())
            async with session_manager.session() as session:
                existing_row = await session.get(
                    NoteTitleTranscriptDO, (user_id, file_id, bitmap_md5)
                )
                if existing_row is None:
                    session.add(
                        NoteTitleTranscriptDO(
                            user_id=user_id,
                            file_id=file_id,
                            bitmap_md5=bitmap_md5,
                            text_content=normalized_text,
                        )
                    )
                else:
                    existing_row.text_content = normalized_text
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
    """Register `OcrModule` with the `"processor"` platform."""
    registrar.register_module(
        OcrModule(
            file_service=core.file_service,
            ocr_model=core.app.get(OCR_MODEL_KEY),
            note_metadata_service=core.app.get(NOTE_METADATA_SERVICE_KEY),
        )
    )
