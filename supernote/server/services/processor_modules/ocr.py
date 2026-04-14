import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.ai_service import AIService
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_content_by_id,
)
from supernote.server.utils.paths import get_page_png_path
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

logger = logging.getLogger(__name__)


@dataclass
class PageMetadata:
    file_name: str | None
    page_index: int
    page_id: str
    notebook_create_time: int | None

    @property
    def file_name_basis(self) -> str | None:
        if self.file_name:
            return Path(self.file_name).stem.lower()
        return None


def _build_ocr_prompt(page_metadata: PageMetadata) -> str:
    prompt = PROMPT_LOADER.get_prompt(
        PromptId.OCR_TRANSCRIPTION, custom_type=page_metadata.file_name_basis
    )
    metadata_block = format_page_metadata(
        page_index=page_metadata.page_index,
        page_id=page_metadata.page_id,
        file_name=page_metadata.file_name,
        notebook_create_time=page_metadata.notebook_create_time,
        include_section_divider=True,
    )
    return f"{metadata_block}\n\n{prompt}"


class OcrModule(ProcessorModule):
    """Module responsible for extracting text from note pages using AI OCR."""

    def __init__(
        self,
        file_service: FileService,
        ai_service: AIService,
    ) -> None:
        self.file_service = file_service
        self.ai_service = ai_service

    @property
    def name(self) -> str:
        return "OcrModule"

    @property
    def task_type(self) -> str:
        return "OCR_EXTRACTION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> bool:
        if page_index is None:
            return False

        if not self.ai_service.is_configured:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, page_id
        ):
            return False

        if not page_id:
            return False

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
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        if page_id is None:
            logger.error(f"Page ID required for OCR processing of file {file_id}")
            return

        png_path = get_page_png_path(file_id, page_id)
        chunks = []
        async for chunk in self.file_service.blob_storage.get(CACHE_BUCKET, png_path):
            chunks.append(chunk)
        png_data = b"".join(chunks)

        if not self.ai_service.is_configured:
            raise ValueError("AI service not configured")

        file_name: Optional[str] = None
        notebook_create_time: Optional[int] = None
        async with session_manager.session() as session:
            file_do = await session.get(UserFileDO, file_id)
            if file_do:
                file_name = file_do.file_name
                notebook_create_time = file_do.create_time

        page_metadata = PageMetadata(
            file_name=file_name,
            page_index=page_index or 0,
            page_id=page_id,
            notebook_create_time=notebook_create_time,
        )
        prompt = _build_ocr_prompt(page_metadata)
        text_content = await self.ai_service.ocr_image(png_data, prompt)

        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            if content:
                content.text_content = text_content
            else:
                logger.warning(
                    f"NotePageContentDO missing for {file_id} page {page_id} during OCR"
                )
            await session.commit()

        logger.info(f"Completed OCR for file {file_id} page {page_id}")
