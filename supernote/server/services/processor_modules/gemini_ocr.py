import logging
from typing import Optional

from google.genai import types

from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.gemini_content import PageMetadata, create_gemini_content
from supernote.server.utils.note_content import (
    get_page_content_by_id,
)
from supernote.server.utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


class GeminiOcrModule(ProcessorModule):
    """Module responsible for extracting text from note pages using Gemini OCR."""

    def __init__(
        self,
        file_service: FileService,
        config: ServerConfig,
        gemini_service: GeminiService,
    ) -> None:
        self.file_service = file_service
        self.config = config
        self.gemini_service = gemini_service

    @property
    def name(self) -> str:
        return "GeminiOcrModule"

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

        if not self.gemini_service.is_configured:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, page_id
        ):
            return False

        if not page_id:
            return False

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
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        if page_id is None:
            logger.error(f"Page ID required for OCR processing of file {file_id}")
            return

        # Get PNG Content
        png_path = get_page_png_path(file_id, page_id)
        png_data = b""
        async for chunk in self.file_service.blob_storage.get(CACHE_BUCKET, png_path):
            png_data += chunk

        # Call Gemini API
        if not self.gemini_service.is_configured:
            raise ValueError("Gemini API key not configured")

        # Get File Info for custom prompt and metadata
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
        model_id = self.config.gemini_ocr_model
        parts = create_gemini_content(page_metadata, png_data)
        response = await self.gemini_service.generate_content(
            model=model_id,
            contents=[
                types.Content(
                    parts=parts,
                )
            ],
            config={"media_resolution": "media_resolution_high"},  # type: ignore[arg-type]
        )

        text_content = response.text if response.text else ""

        # Save Result
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
