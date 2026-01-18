import json
import logging
from typing import Optional

from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import get_page_content_by_id

logger = logging.getLogger(__name__)


class GeminiEmbeddingModule(ProcessorModule):
    """Module responsible for generating embeddings for note pages using Gemini."""

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
        return "GeminiEmbeddingModule"

    @property
    def task_type(self) -> str:
        return "EMBEDDING_GENERATION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> bool:
        if not page_id:
            return False

        if not self.gemini_service.is_configured:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, page_id
        ):
            return False

        async with session_manager.session() as session:
            # Check Prerequisites (Text Content must exist)
            content = await get_page_content_by_id(session, file_id, page_id)

            if not content or not content.text_content:
                # Dependency not met yet (OCR not done or empty page)
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
        if not page_id:
            return

        # Get Text Content
        text_content = ""
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)

            if not content or not content.text_content:
                logger.warning(
                    f"No text content found for embedding: file {file_id} page {page_id} (idx {page_index})"
                )
                return
            text_content = content.text_content

        # Call Gemini API
        if not self.gemini_service.is_configured:
            raise ValueError("Gemini API key not configured")

        model_id = self.config.gemini_embedding_model
        response = await self.gemini_service.embed_content(
            model=model_id,
            contents=text_content,
        )

        if not response.embeddings:
            raise ValueError("No embeddings returned from Gemini API")

        # Assuming single embedding for the whole text block for now
        embedding_values = response.embeddings[0].values
        embedding_json = json.dumps(embedding_values)

        # Save Result
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)

            if content:
                content.embedding = embedding_json
            await session.commit()

        logger.info(f"Completed Embedding for file {file_id} page {page_index}")
