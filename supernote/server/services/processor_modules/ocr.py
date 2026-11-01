import logging

from supernote.models.base import TaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import get_page_content_by_id
from supernote.server.utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


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
            if content is not None and content.has_ink is False:
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

        # Get File Info & Page Context (has_ink, page_style)
        file_name: str | None = None
        notebook_create_time: int | None = None
        page_style: str | None = None
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)
            if content is not None and content.has_ink is False:
                content.text_content = ""
                await session.commit()
                logger.info(
                    f"Skipping OCR LLM call for blank page {page_id} of file {file_id}"
                )
                return
            if content is not None:
                page_style = content.page_style

            file_do = await session.get(UserFileDO, file_id)
            if file_do:
                file_name = file_do.file_name
                notebook_create_time = file_do.create_time

        # Get PNG Content
        png_path = get_page_png_path(file_id, page_id)
        chunks = [
            chunk
            async for chunk in self.file_service.blob_storage.get(
                CACHE_BUCKET, png_path
            )
        ]
        png_data = b"".join(chunks)

        page_metadata = PageMetadata(
            file_name=file_name,
            page_index=page_index or 0,
            page_id=page_id,
            notebook_create_time=notebook_create_time,
            page_style=page_style,
        )
        prompt = format_ocr_prompt(page_metadata)
        text_content = await self.ocr_model.extract_text(png_data, prompt)

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
