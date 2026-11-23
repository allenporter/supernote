"""Stage 3 of the `.note` processing pipeline: vision-model OCR extraction (`TaskType.OCR_EXTRACTION`).

`OcrModule` loads the cached page PNG from `CACHE_BUCKET`, formats a notebook-aware
transcription prompt via `supernote.server.ai.prompts.format_ocr_prompt` (routing custom
prompts through `supernote.server.utils.prompt_loader.PROMPT_LOADER`), and invokes
`supernote.server.ai.models.ocr.OcrModel.extract_text`. The resulting Markdown transcript
is saved to `NotePageContentDO.text_content`. See `supernote.guides.mcp`.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import TaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NotePageTranscribedEvent
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
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


class OcrModule(ProcessorModule):
    """Module responsible for extracting text from note pages using an `OcrModel`."""

    def __init__(
        self,
        file_service: FileService,
        ocr_model: OcrModel | None,
    ) -> None:
        self.file_service = file_service
        self.ocr_model = ocr_model

    @property
    def name(self) -> str:
        return "OcrModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.OCR_EXTRACTION

    @property
    def enabled(self) -> bool:
        return self.ocr_model is not None

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        if page_index is None:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, page_id
        ):
            return False

        if not page_id:
            return False

        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            if content is None:
                logger.warning(
                    f"Page content prerequisite not met for OCR of {file_id} page {page_id}"
                )
                return False
            file_do = await session.get(UserFileDO, file_id)
            if file_do is None:
                return False
            page_meta = await _get_verified_page_metadata(
                session, file_do.user_id, file_id, page_id, content.content_hash
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
            prompt = format_ocr_prompt(page_metadata)

        png_path = get_page_png_path(file_id, page_id)
        chunks = [
            chunk
            async for chunk in self.file_service.blob_storage.get(
                CACHE_BUCKET, png_path
            )
        ]
        png_data = b"".join(chunks)
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

        logger.info(f"Completed OCR for file {file_id} page {page_id}")

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
