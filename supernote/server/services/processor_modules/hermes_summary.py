"""Processor module that generates a Hermes-powered interpretation summary.

Runs after OCR/embedding (and independently of the Gemini-based
``SummaryModule``) to turn a note's OCR transcript into an interpreted
Markdown summary via ``HermesSummaryService``, storing the result as a
separate summary row without ever touching the raw OCR transcript summary.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

from sqlalchemy import select

from supernote.models.summary import AddSummaryDTO, AddSummaryGroupDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.hermes_summary import HermesSummaryService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.note_content import format_page_metadata
from supernote.server.utils.paths import get_hermes_summary_id, get_summary_group_id

logger = logging.getLogger(__name__)

# Keys used in the Hermes summary's `extra_metadata` JSON blob.
METADATA_SOURCE_HASH = "source_hash"
METADATA_GENERATED_AT = "generated_at"
METADATA_PAGE_COUNT = "page_count"


class HermesSummaryModule(ProcessorModule):
    """Module responsible for generating a Hermes interpretation summary for a note.

    Mirrors ``SummaryModule`` (the Gemini-based summary generator) in
    structure, but is entirely independent of it:

    - Gated by its own feature flag (``hermes_summary_enabled``), not Gemini
      configuration, so it runs even when the Gemini summary is disabled.
    - Never touches the ``data_source == "OCR"`` transcript summary.
    - Stores its output as a separate ``data_source == "HERMES_INTERPRETATION"``
      summary row, in the same summary group as the OCR/AI summaries.

    Idempotency note: unlike most modules, this one does NOT rely on the base
    class's default "skip once COMPLETED" gating. Instead, `run_if_needed`
    always re-checks (when enabled and OCR text exists), and `process()`
    compares a combined source hash against the hash stored in the existing
    Hermes summary's metadata to decide whether regeneration is actually
    needed. This is what allows content changes to trigger regeneration even
    though the task was already marked COMPLETED once.
    """

    def __init__(
        self,
        file_service: FileService,
        config: ServerConfig,
        hermes_summary_service: HermesSummaryService,
        summary_service: SummaryService,
    ) -> None:
        self.file_service = file_service
        self.config = config
        self.hermes_summary_service = hermes_summary_service
        self.summary_service = summary_service

    @property
    def name(self) -> str:
        return "HermesSummaryModule"

    @property
    def task_type(self) -> str:
        return "HERMES_SUMMARY_GENERATION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Determines if Hermes summary generation is needed."""
        # Hermes summary is a file-level task (global), not page-level.
        if page_index is not None:
            return False

        if not self.config.hermes_summary_enabled:
            return False

        # Skip if no pages have any non-empty OCR text yet.
        async with session_manager.session() as session:
            stmt = select(NotePageContentDO.text_content).where(
                NotePageContentDO.file_id == file_id
            )
            result = await session.execute(stmt)
            texts = result.scalars().all()

        if not any(texts):
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
        """Generates a Hermes interpretation summary for the given file.

        1. Aggregates all OCR text for the file into a page-marked transcript.
        2. Computes a combined source hash and no-ops if it matches the hash
           already stored in the existing Hermes summary row's metadata
           (idempotency across reruns).
        3. Calls `HermesSummaryService.generate_interpretation(...)`.
        4. Stores the result as a `data_source = "HERMES_INTERPRETATION"`
           summary row via `SummaryService.upsert_group`/`upsert_summary`,
           never touching the `data_source = "OCR"` transcript summary.
        """
        logger.info(f"Starting Hermes summary generation for file_id={file_id}")

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

            stmt = (
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            pages = result.scalars().all()

        if not pages or not any(p.text_content for p in pages):
            logger.info(
                f"No OCR text found for file {file_id}. Skipping Hermes summary."
            )
            return

        # Key generation, matching SummaryModule/SummaryService conventions.
        file_basis = file_do.storage_key or str(file_do.id)
        group_uuid = get_summary_group_id(file_basis)
        group_name = Path(file_do.file_name).name
        group_md5 = hashlib.md5(group_name.encode("utf-8")).hexdigest()
        hermes_uuid = get_hermes_summary_id(file_basis)

        # Build the page-marked transcript, same formatting SummaryModule uses.
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

        # Combined source hash: storage key/md5 basis + page ids + per-page
        # content hashes/OCR text. Used purely to detect whether the Hermes
        # summary needs regenerating -- persisted only in this summary's own
        # metadata, never in `f_system_task`.
        hasher = hashlib.md5()
        hasher.update(file_basis.encode("utf-8"))
        for p in pages:
            hasher.update((p.page_id or "").encode("utf-8"))
            hasher.update((p.content_hash or "").encode("utf-8"))
            hasher.update((p.text_content or "").encode("utf-8"))
        source_hash = hasher.hexdigest()

        existing = await self.summary_service.get_summary_by_uuid(
            user_email, hermes_uuid
        )
        existing_metadata: dict[str, object] = {}
        if existing and existing.metadata:
            try:
                existing_metadata = json.loads(existing.metadata)
            except (json.JSONDecodeError, TypeError):
                existing_metadata = {}

        if existing and existing_metadata.get(METADATA_SOURCE_HASH) == source_hash:
            logger.info(
                f"Hermes summary for file {file_id} is unchanged (source hash "
                "match). Skipping regeneration."
            )
            return

        # Ensure the summary group exists -- HermesSummaryModule must work
        # even when SummaryModule (Gemini) never ran (e.g. disabled/unconfigured).
        await self.summary_service.upsert_group(
            user_email,
            AddSummaryGroupDTO(
                unique_identifier=group_uuid,
                name=group_name,
                md5_hash=group_md5,
            ),
        )

        # No try/except here: exceptions bubble up so the base class's `run()`
        # marks the task FAILED (with the error message) and it becomes
        # eligible for automatic retry, per the ProcessorModule contract.
        interpretation = await self.hermes_summary_service.generate_interpretation(
            file_id=file_id,
            file_name=file_do.file_name,
            transcript=full_text,
            page_count=len(pages),
            existing_context_hint=existing.content if existing else None,
        )

        metadata_str = json.dumps(
            {
                METADATA_SOURCE_HASH: source_hash,
                METADATA_GENERATED_AT: int(time.time() * 1000),
                METADATA_PAGE_COUNT: len(pages),
            }
        )

        await self.summary_service.upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=hermes_uuid,
                parent_unique_identifier=group_uuid,
                content=interpretation,
                data_source="HERMES_INTERPRETATION",
                source_path=file_do.file_name,
                metadata=metadata_str,
            ),
        )
