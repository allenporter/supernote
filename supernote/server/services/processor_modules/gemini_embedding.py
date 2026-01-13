import json
import logging
from typing import Optional

from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import get_page_content
from supernote.server.utils.tasks import get_task, update_task_status

logger = logging.getLogger(__name__)


class GeminiEmbeddingModule(ProcessorModule):
    """Module responsible for generating embeddings for note pages using Gemini.

    This module performs the following:
    1.  Reads the transcribed text from `NotePageContentDO`.
    2.  Sends the text to the Gemini API (using the configured embedding model).
    3.  Updates the `NotePageContentDO` with the embedding (JSON string).
    4.  Updates the `SystemTaskDO` status to COMPLETED.
    """

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
    ) -> bool:
        if page_index is None:
            return False

        task_key = f"page_{page_index}"
        task = await get_task(session_manager, file_id, self.task_type, task_key)

        if task and task.status == "COMPLETED":
            return False

        async with session_manager.session() as session:
            # Check Prerequisites (Text Content must exist)
            content = await get_page_content(session, file_id, page_index)
            if not content or not content.text_content:
                # Dependency not met yet (OCR not done or empty page)
                return False

        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        if page_index is None:
            return

        task_key = f"page_{page_index}"
        logger.info(f"Starting Embedding for file {file_id} page {page_index}")

        # 1. Get Text Content
        text_content = ""
        async with session_manager.session() as session:
            content = await get_page_content(session, file_id, page_index)
            if not content or not content.text_content:
                logger.warning(
                    f"No text content found for embedding: file {file_id} page {page_index}"
                )
                return
            text_content = content.text_content

        # 2. Call Gemini API
        try:
            if not self.gemini_service.is_configured:
                raise ValueError("Gemini API key not configured")

            model_id = self.config.gemini_embedding_model

            # Use shared service
            response = await self.gemini_service.embed_content(
                model=model_id,
                contents=text_content,
            )

            if not response.embeddings:
                raise ValueError("No embeddings returned from Gemini API")

            # Assuming single embedding for the whole text block for now
            embedding_values = response.embeddings[0].values
            embedding_json = json.dumps(embedding_values)

        except Exception as e:
            logger.error(f"Gemini API failed for {file_id} page {page_index}: {e}")
            await update_task_status(
                session_manager, file_id, self.task_type, task_key, "FAILED", str(e)
            )
            return

        # 3. Save Result
        async with session_manager.session() as session:
            content = await get_page_content(session, file_id, page_index)

            if content:
                content.embedding = embedding_json

            await session.commit()

        # 4. Update Task Status
        await update_task_status(
            session_manager, file_id, self.task_type, task_key, "COMPLETED"
        )
        logger.info(f"Completed Embedding for file {file_id} page {page_index}")
