import logging

from supernote.models.base import TaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.vocabulary import VocabularyService
from supernote.server.utils.note_content import get_page_content_by_id
from supernote.server.utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


class OcrModule(ProcessorModule):
    """Module responsible for extracting text from note pages using an `OcrModel`."""

    def __init__(
        self,
        file_service: FileService,
        ocr_model: OcrModel | None,
        vocabulary_service: VocabularyService | None = None,
    ) -> None:
        self.file_service = file_service
        self.ocr_model = ocr_model
        self.vocabulary_service = vocabulary_service

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

        # Get PNG Content
        png_path = get_page_png_path(file_id, page_id)
        chunks = [
            chunk
            async for chunk in self.file_service.blob_storage.get(
                CACHE_BUCKET, png_path
            )
        ]
        png_data = b"".join(chunks)

        # Get File Info for custom prompt and metadata
        file_name: str | None = None
        notebook_create_time: int | None = None
        user_id: int | None = None
        async with session_manager.session() as session:
            file_do = await session.get(UserFileDO, file_id)
            if file_do:
                file_name = file_do.file_name
                notebook_create_time = file_do.create_time
                user_id = file_do.user_id

        vocabulary: list[str] = []
        if self.vocabulary_service and user_id is not None:
            vocabulary = await self.vocabulary_service.terms_for_notebook(
                user_id, file_id
            )

        page_metadata = PageMetadata(
            file_name=file_name,
            page_index=page_index or 0,
            page_id=page_id,
            notebook_create_time=notebook_create_time,
        )
        prompt = format_ocr_prompt(page_metadata, vocabulary=vocabulary)
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
