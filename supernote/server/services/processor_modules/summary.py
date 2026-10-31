"""Stage 5 of the `.note` processing pipeline: transcript aggregation and AI summarization (`TaskType.SUMMARY_GENERATION`).

After all pages of a `.note` file have completed OCR, `SummaryModule` assembles the full
page-annotated transcript (`data_source="OCR"`), formats a notebook-specific prompt via
`supernote.server.ai.prompts.format_summary_prompt`, calls
`supernote.server.ai.models.summary.SummaryModel.summarize`, and upserts both the transcript
and date-grouped Markdown summary into `supernote.server.services.summary.SummaryService`.
See `supernote.guides.mcp` and `supernote.guides.summary_api`.
"""

import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import select

from supernote.models.base import TaskType
from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import format_summary_prompt
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.note_content import format_page_metadata
from supernote.server.utils.paths import (
    get_summary_group_id,
    get_summary_id,
    get_transcript_id,
)

__all__ = [
    "SummaryModule",
]

logger = logging.getLogger(__name__)


class SummaryModule(ProcessorModule):
    """Module responsible for aggregating OCR text and generating summaries for a note."""

    def __init__(
        self,
        file_service: FileService,
        summary_service: SummaryService,
        summary_model: SummaryModel | None,
    ) -> None:
        self.file_service = file_service
        self.summary_service = summary_service
        self.summary_model = summary_model

    @property
    def name(self) -> str:
        return "SummaryModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.SUMMARY_GENERATION

    @property
    def enabled(self) -> bool:
        return self.summary_model is not None

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Determines if summary generation is needed."""
        # Summary is a file-level task (global), not page-level.
        if page_index is not None:
            return False

        if not await super().run_if_needed(file_id, session_manager, page_index):
            return False

        async with session_manager.session() as session:
            pages = (
                (
                    await session.execute(
                        select(NotePageContentDO.text_content).where(
                            NotePageContentDO.file_id == file_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not pages:
                logger.debug(
                    f"No pages found for file {file_id}; skipping summary generation"
                )
                return False
            missing_count = sum(1 for text in pages if text is None)
            if missing_count > 0:
                logger.warning(
                    f"OCR prerequisite not met for summary of file {file_id} "
                    f"({missing_count}/{len(pages)} pages missing text)"
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
        """Aggregate OCR text for the file and store transcript and AI summary records."""
        if self.summary_model is None:
            raise ValueError("Summary model not configured")

        logger.info(f"Starting summary generation for file_id={file_id}")

        async with session_manager.session() as session:
            file_do = await session.get(UserFileDO, file_id)
            if not file_do:
                logger.error(f"File {file_id} not found.")
                return

            user: UserDO | None = await session.get(UserDO, file_do.user_id)
            if not user or not user.email:
                logger.error(f"User for file {file_id} not found.")
                return
            user_email = user.email

            file_basis = file_do.storage_key or str(file_do.id)
            group_uuid = get_summary_group_id(file_basis)
            group_name = Path(file_do.file_name).name
            group_md5 = hashlib.md5(group_name.encode("utf-8")).hexdigest()
            summary_uuid = get_summary_id(file_basis)
            transcript_uuid = get_transcript_id(file_basis)

            stmt = (
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            pages = result.scalars().all()

        if not pages:
            logger.info(f"No OCR pages found for file {file_id}. Skipping summary.")
            return

        # Format transcript with Page markers and inferred dates
        text_parts = []
        for p in pages:
            if p.text_content:
                metadata = format_page_metadata(
                    page_index=p.page_index,
                    page_id=p.page_id or "",
                    file_name=file_do.file_name,
                    notebook_create_time=file_do.create_time,
                    include_section_divider=True,
                )
                text_parts.append(f"{metadata}\n{p.text_content}")

        full_text = "\n\n".join(text_parts)

        await self._upsert_group(
            user_email,
            AddSummaryGroupDTO(
                unique_identifier=group_uuid,
                name=group_name,
                md5_hash=group_md5,
            ),
        )

        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=transcript_uuid,
                parent_unique_identifier=group_uuid,
                content=full_text,
                data_source="OCR",
                source_path=file_do.file_name,
            ),
        )

        custom_type = Path(file_do.file_name).stem.lower()
        prompt = format_summary_prompt(full_text, custom_type=custom_type)
        summary_response = await self.summary_model.summarize(prompt)

        # Format segments into Markdown and collect metadata
        ai_summary = "No summary generated."
        metadata_str = None

        summary_parts = []
        clean_segments = []

        for seg in summary_response.segments:
            date_range = seg.date_range or "Unknown Date"
            text = (seg.summary or "").replace("\\n", "\n")
            dates = seg.extracted_dates or []
            page_refs = seg.page_refs or []

            # Markdown Formatting
            header = f"## {date_range}"
            # Add page citations to markdown too for readability
            if page_refs:
                # e.g. (Pages 45, 46)
                pages_str = ", ".join(str(p) for p in page_refs)
                header += f" (Pages {pages_str})"

            summary_parts.append(f"{header}\n{text}")

            clean_segments.append(
                {
                    "date_range": date_range,
                    "summary": text,
                    "extracted_dates": dates,
                    "page_refs": page_refs,
                }
            )

        if summary_parts:
            ai_summary = "\n\n".join(summary_parts)

        # Construct rich metadata for retrieval
        if clean_segments:
            meta_obj = {METADATA_SEGMENTS: clean_segments}
            metadata_str = json.dumps(meta_obj)
            logger.info(
                f"Generated metadata for file {file_id}: segments={len(clean_segments)}"
            )

        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=summary_uuid,
                parent_unique_identifier=group_uuid,
                content=ai_summary,
                data_source=self.summary_model.model_id,
                source_path=file_do.file_name,
                metadata=metadata_str,
            ),
        )

    async def _upsert_group(self, user_email: str, dto: AddSummaryGroupDTO) -> None:
        """Helper to either add or update a summary group based on its unique identifier."""
        if not dto.unique_identifier:
            logger.error("Cannot upsert summary group without a unique identifier")
            return

        existing = await self.summary_service.get_summary_by_uuid(
            user_email, dto.unique_identifier
        )
        if existing and existing.id is not None:
            await self.summary_service.update_group(
                user_email,
                UpdateSummaryGroupDTO(
                    id=existing.id,
                    unique_identifier=dto.unique_identifier,
                    name=dto.name,
                    md5_hash=dto.md5_hash,
                    description=dto.description,
                ),
            )
        else:
            await self.summary_service.add_group(user_email, dto)

    async def _upsert_summary(self, user_email: str, dto: AddSummaryDTO) -> None:
        """Helper to either add or update a summary based on its unique identifier."""
        if not dto.unique_identifier:
            logger.error("Cannot upsert summary without a unique identifier")
            return

        existing = await self.summary_service.get_summary_by_uuid(
            user_email, dto.unique_identifier
        )
        if existing and existing.id is not None:
            await self.summary_service.update_summary(
                user_email,
                UpdateSummaryDTO(
                    id=existing.id,
                    parent_unique_identifier=dto.parent_unique_identifier,
                    content=dto.content,
                    data_source=dto.data_source,
                    source_path=dto.source_path,
                    metadata=dto.metadata,
                ),
            )
        else:
            await self.summary_service.add_summary(user_email, dto)
