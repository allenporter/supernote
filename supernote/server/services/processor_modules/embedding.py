"""Stage 4 of the `.note` processing pipeline: page vector embedding generation (`TaskType.EMBEDDING_GENERATION`).

`EmbeddingModule` reads the OCR transcript from `NotePageContentDO.text_content`, calls
`supernote.server.ai.models.embedding.EmbeddingModel.embed` with `EmbeddingTaskType.RETRIEVAL_DOCUMENT`,
and stores the vector and `model_id` on `NotePageContentDO`. Because `EmbeddingModule.version`
returns `embedding_model.model_id`, changing `ai.embedding.model` in `ServerConfig`
automatically triggers background re-embedding of all pages. See `supernote.guides.mcp`.
"""

import json
import logging

from supernote.models.base import TaskType
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.note_content import get_page_content_by_id

logger = logging.getLogger(__name__)


class EmbeddingModule(ProcessorModule):
    """Module responsible for generating embeddings for note pages using an `EmbeddingModel`."""

    def __init__(
        self,
        file_service: FileService,
        embedding_model: EmbeddingModel | None,
    ) -> None:
        self.file_service = file_service
        self.embedding_model = embedding_model

    @property
    def name(self) -> str:
        return "EmbeddingModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.EMBEDDING_GENERATION

    @property
    def enabled(self) -> bool:
        return self.embedding_model is not None

    @property
    def version(self) -> str | None:
        return self.embedding_model.model_id if self.embedding_model else None

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        if not page_id:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, page_id
        ):
            return False

        async with session_manager.session() as session:
            # Check Prerequisites (OCR must have run so text_content is not None)
            content = await get_page_content_by_id(session, file_id, page_id)
            if not content or content.text_content is None:
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

        if self.embedding_model is None:
            raise ValueError("Embedding model not configured")

        # Get Text Content
        text_content = ""
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)

            if not content or not content.text_content:
                logger.debug(
                    f"No text content to embed for file {file_id} page {page_id} (idx {page_index})"
                )
                return
            text_content = content.text_content

        embedding_values = await self.embedding_model.embed(
            text_content, task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
        )
        embedding_json = json.dumps(embedding_values)

        # Save Result
        async with session_manager.session() as session:
            content = await get_page_content_by_id(session, file_id, page_id)

            if content:
                content.embedding = embedding_json
                content.embedding_model = self.embedding_model.model_id
            await session.commit()

        logger.info(f"Completed Embedding for file {file_id} page {page_index}")
