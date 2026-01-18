import logging
from typing import Optional

from sqlalchemy import select

from supernote.models.summary import AddSummaryDTO, UpdateSummaryDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.summary import SummaryService

logger = logging.getLogger(__name__)


class SummaryModule(ProcessorModule):
    """Module responsible for aggregating OCR text and generating summaries for a note."""

    def __init__(
        self,
        file_service: FileService,
        config: ServerConfig,
        gemini_service: GeminiService,
        summary_service: SummaryService,
    ) -> None:
        self.file_service = file_service
        self.config = config
        self.gemini_service = gemini_service
        self.summary_service = summary_service

    @property
    def name(self) -> str:
        return "SummaryModule"

    @property
    def task_type(self) -> str:
        return "SUMMARY_GENERATION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        # Summary is a file-level task (global), not page-level.
        if page_index is not None:
            return False

        if not self.gemini_service.is_configured:
            return False

        if not await super().run_if_needed(file_id, session_manager, page_index):
            return False

        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        """Aggregate OCR text and generate summaries."""
        async with session_manager.session() as session:
            # 1. Get File Info and User Email
            stmt = (
                select(UserFileDO, UserDO.email)
                .join(UserDO, UserFileDO.user_id == UserDO.id)
                .where(UserFileDO.id == file_id)
            )
            result = await session.execute(stmt)
            row = result.first()
            if not row:
                logger.error(
                    f"File {file_id} or owner not found for summary generation"
                )
                return
            file_do, user_email = row

            # 2. Aggregate OCR Text
            stmt = (
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index.asc())
            )
            result = await session.execute(stmt)
            pages = result.scalars().all()

            text_parts = []
            for page in pages:
                if page.text_content:
                    text_parts.append(
                        f"--- Page {page.page_index + 1} ---\n{page.text_content}"
                    )

            full_text = "\n\n".join(text_parts)
            if not full_text:
                logger.info(f"No text content to summarize for file {file_id}")
                return

        # Use storage_key or ID as basis for stable UUIDs
        file_basis = file_do.storage_key or str(file_do.id)

        # 3. Create/Update Transcript Summary
        transcript_uuid = f"{file_basis}-transcript"
        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=transcript_uuid,
                content=full_text,
                data_source="OCR",
                source_path=file_do.file_name,
            ),
        )

        # 4. Create/Update AI Insights Summary
        if not self.gemini_service.is_configured:
            return

        summary_uuid = f"{file_basis}-summary"

        prompt = (
            "You are a helpful assistant summarizing handwritten notes from a Supernote device. "
            "Below is the OCR transcript of a notebook. Please provide a concise summary including: "
            "1. Key Topics discussed. "
            "2. Action Items or Tasks. "
            "3. Decisions made. "
            "Use Markdown for formatting."
            "\n\nTranscript:\n" + full_text
        )

        try:
            response = await self.gemini_service.generate_content(
                model=self.config.gemini_ocr_model,
                contents=prompt,
            )
            ai_summary = response.text if response.text else "No summary generated."

            await self._upsert_summary(
                user_email,
                AddSummaryDTO(
                    file_id=file_id,
                    unique_identifier=summary_uuid,
                    content=ai_summary,
                    data_source="GEMINI",
                    source_path=file_do.file_name,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to generate AI summary for file {file_id}: {e}")

    async def _upsert_summary(self, user_email: str, dto: AddSummaryDTO) -> None:
        """Helper to either add or update a summary based on its unique identifier."""
        existing = await self.summary_service.get_summary_by_uuid(
            user_email, dto.unique_identifier
        )
        if existing:
            await self.summary_service.update_summary(
                user_email,
                UpdateSummaryDTO(
                    id=existing.id,
                    content=dto.content,
                    data_source=dto.data_source,
                    source_path=dto.source_path,
                ),
            )
        else:
            await self.summary_service.add_summary(user_email, dto)
