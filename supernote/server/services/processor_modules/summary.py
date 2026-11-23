"""Stage 5 of the `.note` processing pipeline: AI notebook summarization (`TaskType.SUMMARY_GENERATION`).

After all pages of a `.note` file have completed OCR, `SummaryModule` assembles the full
page-annotated transcript in memory from `NotePageContentDO`, formats a notebook-specific prompt
via `supernote.server.ai.prompts.format_summary_prompt`, calls
`supernote.server.ai.models.summary.SummaryModel.summarize`, and upserts the date-grouped
Markdown summary under the shared `"AI Summaries"` Digest category (`SummaryGroup`) via
`supernote.server.services.summary.SummaryService`.
See `supernote.guides.mcp` and `supernote.guides.summary_api`.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import delete, select

from supernote.models.base import TaskType
from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
    SummaryItem,
    UpdateSummaryDTO,
)
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import format_summary_prompt
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import SummaryDeletedEvent
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_keywords_map,
)
from supernote.server.utils.paths import (
    AI_SUMMARIES_GROUP_NAME,
    flatten_vfs_path,
    get_ai_summaries_group_id,
    get_summary_id,
)

__all__ = [
    "SummaryModule",
]

logger = logging.getLogger(__name__)


def _has_raw_annotations(
    comment_str: str | None,
    comment_handwrite_name: str | None,
    handwrite_inner_name: str | None,
) -> bool:
    """Return True if any user comment or handwriting field is non-empty."""
    return any(
        (val or "").strip()
        for val in (comment_str, comment_handwrite_name, handwrite_inner_name)
    )


def _has_user_annotations(item: SummaryItem) -> bool:
    """Return True if a summary or group carries user comments or handwriting."""
    return _has_raw_annotations(
        item.comment_str, item.comment_handwrite_name, item.handwrite_inner_name
    )


def _is_legacy_group_uuid(unique_identifier: str | None) -> bool:
    """Return True for legacy per-file `-group` summary group identifiers."""
    return bool(unique_identifier) and unique_identifier.endswith("-group")


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
        self._group_lock = asyncio.Lock()

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

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete unannotated generated summaries and empty legacy groups while detaching user Digests."""
        deleted_events: list[SummaryDeletedEvent] = []
        summary_uuid = get_summary_id(user_id, file_id)
        async with session_manager.session() as session:
            summary_rows = (
                (
                    await session.execute(
                        select(SummaryDO).where(
                            SummaryDO.user_id == user_id,
                            SummaryDO.file_id == file_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            ids_to_delete: list[int] = []
            parent_uuids: set[str] = set()
            for row in summary_rows:
                is_generated = not row.is_summary_group and (
                    row.unique_identifier == summary_uuid
                    or (row.data_source or "").upper() == "OCR"
                    or row.unique_identifier.endswith(("-transcript", "-summary"))
                )
                has_annotations = _has_raw_annotations(
                    row.comment_str,
                    row.comment_handwrite_name,
                    row.handwrite_inner_name,
                )
                if not is_generated or has_annotations:
                    row.file_id = None
                    continue

                ids_to_delete.append(int(row.id))
                if row.parent_unique_identifier and _is_legacy_group_uuid(
                    row.parent_unique_identifier
                ):
                    parent_uuids.add(row.parent_unique_identifier)
                if not row.is_deleted:
                    deleted_events.append(
                        SummaryDeletedEvent(
                            user_id=user_id,
                            summary_id=int(row.id),
                            is_summary_group=False,
                            file_id=file_id,
                            unique_identifier=row.unique_identifier,
                        )
                    )

            if ids_to_delete:
                await session.execute(
                    delete(SummaryDO).where(
                        SummaryDO.user_id == user_id,
                        SummaryDO.id.in_(ids_to_delete),
                    )
                )

            if parent_uuids:
                surviving_parent_stmt = (
                    select(SummaryDO.parent_unique_identifier)
                    .where(
                        SummaryDO.user_id == user_id,
                        SummaryDO.parent_unique_identifier.in_(parent_uuids),
                    )
                    .group_by(SummaryDO.parent_unique_identifier)
                )
                surviving_parents = {
                    u
                    for u in (await session.execute(surviving_parent_stmt))
                    .scalars()
                    .all()
                    if u
                }
                empty_parent_uuids = parent_uuids - surviving_parents
                if empty_parent_uuids:
                    group_rows = (
                        (
                            await session.execute(
                                select(SummaryDO).where(
                                    SummaryDO.user_id == user_id,
                                    SummaryDO.unique_identifier.in_(empty_parent_uuids),
                                    SummaryDO.is_summary_group.is_(True),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    group_ids_to_delete: list[int] = []
                    for g_row in group_rows:
                        if _has_raw_annotations(
                            g_row.comment_str,
                            g_row.comment_handwrite_name,
                            g_row.handwrite_inner_name,
                        ):
                            continue
                        group_ids_to_delete.append(int(g_row.id))
                        if not g_row.is_deleted:
                            deleted_events.append(
                                SummaryDeletedEvent(
                                    user_id=user_id,
                                    summary_id=int(g_row.id),
                                    is_summary_group=True,
                                    file_id=file_id,
                                    unique_identifier=g_row.unique_identifier,
                                )
                            )
                    if group_ids_to_delete:
                        await session.execute(
                            delete(SummaryDO).where(
                                SummaryDO.user_id == user_id,
                                SummaryDO.id.in_(group_ids_to_delete),
                            )
                        )
            await session.commit()

        if self.summary_service.event_bus is not None:
            for ev in deleted_events:
                await self.summary_service.event_bus.publish(ev)

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Aggregate OCR text in memory and upsert the notebook's AI summary record."""
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
            user_id = file_do.user_id

            stmt = (
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            pages = result.scalars().all()
            keywords_map = await get_page_keywords_map(session, user_id, file_id)

        if not pages:
            logger.info(f"No OCR pages found for file {file_id}. Skipping summary.")
            return

        # Format transcript with Page markers and inferred dates
        text_parts = []
        for p in pages:
            if not p.is_blank:
                metadata = format_page_metadata(
                    page_index=p.page_index,
                    page_id=p.page_id or "",
                    file_name=file_do.file_name,
                    notebook_create_time=file_do.create_time,
                    keywords=keywords_map.get(p.page_id or ""),
                    include_section_divider=True,
                )
                text_parts.append(f"{metadata}\n{p.text_content}")

        summary_uuid = get_summary_id(user_id, file_id)
        if not text_parts:
            await self._delete_blank_file_summary(user_email, summary_uuid)
            logger.info(
                f"All pages in file {file_id} are blank; skipping summary generation."
            )
            return

        source_path = (
            flatten_vfs_path(
                await self.file_service.get_full_path_by_node(user_id, file_id)
            )
            or file_do.file_name
        )
        full_text = "\n\n".join(text_parts)

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

        await self._upsert_ai_summary(
            user_email=user_email,
            user_id=user_id,
            file_id=file_id,
            summary_uuid=summary_uuid,
            content=ai_summary,
            data_source=self.summary_model.model_id,
            source_path=source_path,
            metadata=metadata_str,
        )

    async def _ensure_ai_summaries_group(self, user_email: str, user_id: int) -> str:
        """Ensure the shared 'AI Summaries' Digest category exists without overwriting user renames."""
        group_uuid = get_ai_summaries_group_id(user_id)
        async with self._group_lock:
            existing = await self.summary_service.get_summary_by_uuid(
                user_email, group_uuid
            )
            if existing is None or existing.id is None:
                group_md5 = hashlib.md5(
                    AI_SUMMARIES_GROUP_NAME.encode("utf-8")
                ).hexdigest()
                await self.summary_service.add_group(
                    user_email,
                    AddSummaryGroupDTO(
                        unique_identifier=group_uuid,
                        name=AI_SUMMARIES_GROUP_NAME,
                        md5_hash=group_md5,
                    ),
                )
        return group_uuid

    async def _upsert_ai_summary(
        self,
        *,
        user_email: str,
        user_id: int,
        file_id: int,
        summary_uuid: str,
        content: str,
        data_source: str,
        source_path: str,
        metadata: str | None,
    ) -> None:
        """Upsert a file's AI summary while preserving manual Partner App category assignments."""
        existing = await self.summary_service.get_summary_by_uuid(
            user_email, summary_uuid
        )
        if existing and existing.id is not None:
            parent_uuid = (
                await self._ensure_ai_summaries_group(user_email, user_id)
                if _is_legacy_group_uuid(existing.parent_unique_identifier)
                else None
            )
            effective_metadata = (
                metadata
                if metadata is not None
                else ("" if existing.metadata else None)
            )
            await self.summary_service.update_summary(
                user_email,
                UpdateSummaryDTO(
                    id=existing.id,
                    parent_unique_identifier=parent_uuid,
                    content=content,
                    data_source=data_source,
                    source_path=source_path,
                    metadata=effective_metadata,
                ),
            )
            return

        group_uuid = await self._ensure_ai_summaries_group(user_email, user_id)
        await self.summary_service.add_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=summary_uuid,
                parent_unique_identifier=group_uuid,
                content=content,
                data_source=data_source,
                source_path=source_path,
                metadata=metadata,
            ),
        )

    async def _delete_blank_file_summary(
        self,
        user_email: str,
        summary_uuid: str,
    ) -> None:
        """Soft-delete a file's unannotated AI summary when all notebook pages become blank."""
        existing = await self.summary_service.get_summary_by_uuid(
            user_email, summary_uuid
        )
        if (
            existing is not None
            and existing.id is not None
            and not _has_user_annotations(existing)
        ):
            await self.summary_service.delete_summary(user_email, existing.id)
