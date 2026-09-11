import json
import logging

from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.ollama import OllamaService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import get_page_content_by_id

logger = logging.getLogger(__name__)


class OllamaEmbeddingModule(ProcessorModule):
    """Module responsible for generating embeddings for note pages using Ollama."""

    def __init__(
        self,
        file_service: FileService,
        config: ServerConfig,
        ollama_service: OllamaService,
    ) -> None:
        self.file_service = file_service
        self.config = config
        self.ollama_service = ollama_service

    @property
    def name(self) -> str:
        return "OllamaEmbeddingModule"

    @property
    def task_type(self) -> str:
        return "EMBEDDING_GENERATION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        if not page_id:
            return False

        if not self.ollama_service.is_configured:
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
        page_index: int | None = None,
        page_id: str | None = None,
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

        # Call Ollama API
        if not self.ollama_service.is_configured:
            raise ValueError("Ollama base URL not configured")

        embedding_values = await self.ollama_service.embed(text_content)
        embedding_json = json.dumps(embedding_values)

        # Save Result
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)

            if content:
                content.embedding = embedding_json
            await session.commit()

        logger.info(f"Completed Embedding for file {file_id} page {page_index}")
