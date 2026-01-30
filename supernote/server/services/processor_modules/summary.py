import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from mashumaro.jsonschema import build_json_schema
from mashumaro.mixins.json import DataClassJSONMixin
from sqlalchemy import select

from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    UpdateSummaryDTO,
)
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.note_content import format_page_metadata
from supernote.server.utils.paths import get_summary_id, get_transcript_id
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

logger = logging.getLogger(__name__)


# Define structured output schema
@dataclass
class SummarySegment(DataClassJSONMixin):
    date_range: str = field(
        metadata={
            "description": "The date range covered by this segment (e.g., '2023-10-27', 'Week of Oct 27')."
        }
    )
    summary: str = field(
        metadata={
            "description": "A concise summary of the events, tasks, and notes for this period."
        }
    )
    extracted_dates: List[str] = field(
        metadata={
            "description": "List of specific dates derived from the content in ISO 8601 format (YYYY-MM-DD)."
        }
    )
    page_refs: List[int] = field(
        metadata={
            "description": "List of 1-indexed page numbers typically found in the text as '--- Page X ---'."
        }
    )


@dataclass
class SummaryResponse(DataClassJSONMixin):
    segments: List[SummarySegment] = field(
        metadata={
            "description": "List of summary segments extracted from the transcript."
        }
    )


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
        page_id: Optional[str] = None,
    ) -> bool:
        """Determines if summary generation is needed."""
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
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        """
        Generates an AI summary for the given file.

        1. Aggregates all OCR text for the file.
        2. Sends to Gemini for summarization and date extraction.
        3. Stores the result as a new Summary.
        """
        logger.info(f"Starting summary generation for file_id={file_id}")

        async with session_manager.session() as session:
            # 1. Fetch File Info
            file_do = await session.get(UserFileDO, file_id)
            if not file_do:
                logger.error(f"File {file_id} not found.")
                return

            user: Optional[UserDO] = await session.get(UserDO, file_do.user_id)
            if not user or not user.email:
                logger.error(f"User for file {file_id} not found.")
                return
            user_email = user.email

            # 2. Key Generation
            file_basis = file_do.storage_key or str(file_do.id)
            summary_uuid = get_summary_id(file_basis)
            transcript_uuid = get_transcript_id(file_basis)

            # 3. Aggregate OCR Text
            # We want to format the text with page markers so the model can cite them.
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

        # 4. Generate Transcript Summary (Preserve existing functionality)
        # Store the raw aggregated text as a 'transcript' summary type first
        # This is a good baseline to have.
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

        # 5. Generate AI Summary using Gemini
        # Determine prompt based on filename/type
        custom_type = Path(file_do.file_name).stem.lower()

        # Load Prompt using specialized logic: Common + (Custom OR Default)
        prompt_template = PROMPT_LOADER.get_prompt(
            PromptId.SUMMARY_GENERATION, custom_type=custom_type
        )
        prompt = f"{prompt_template}\n\nTRANSCRIPT:\n{full_text}"

        try:
            response = await self.gemini_service.generate_content(
                model=self.config.gemini_ocr_model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": build_json_schema(
                        SummaryResponse
                    ).to_dict(),
                },
            )
        except Exception as e:
            logger.error(f"Failed to generate AI summary for file {file_id}: {e}")
            return

        # Parse JSON response
        ai_summary = "No summary generated."
        metadata_str = None

        if response.text:
            try:
                data = json.loads(response.text)
                segments_data = data.get("segments", [])

                # Format segments into Markdown and collect metadata
                summary_parts = []
                all_extracted_dates = []

                # Check for page citations and build clean segment list for metadata
                clean_segments = []

                for seg in segments_data:
                    date_range = seg.get("date_range", "Unknown Date")
                    text = seg.get("summary", "")
                    dates = seg.get("extracted_dates", [])
                    page_refs = seg.get("page_refs", [])

                    # Markdown Formatting
                    header = f"## {date_range}"
                    # Add page citations to markdown too for readability
                    if page_refs:
                        # e.g. (Pages 45, 46)
                        pages_str = ", ".join(str(p) for p in page_refs)
                        header += f" (Pages {pages_str})"

                    summary_parts.append(f"{header}\n{text}")
                    all_extracted_dates.extend(dates)

                    clean_segments.append(
                        {
                            "date_range": date_range,
                            "summary": text,  # Optional: could truncate or omit to save space
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

            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON response for file {file_id}")
                ai_summary = response.text

        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=summary_uuid,
                content=ai_summary,
                data_source="GEMINI",
                source_path=file_do.file_name,
                metadata=metadata_str,
            ),
        )

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
                    content=dto.content,
                    data_source=dto.data_source,
                    source_path=dto.source_path,
                    metadata=dto.metadata,
                ),
            )
        else:
            await self.summary_service.add_summary(user_email, dto)
