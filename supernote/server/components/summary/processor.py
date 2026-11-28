"""Stage 5 of the `.note` processing pipeline: AI notebook summarization (`TaskType.SUMMARY_GENERATION`).

After all pages of a `.note` file have completed OCR, `SummaryModule` assembles the full
page-annotated transcript in memory from `NotePageContentDO`, formats a notebook-specific prompt
via `supernote.server.ai.prompts.format_summary_prompt`, calls
`supernote.server.ai.models.summary.SummaryModel.summarize`, and upserts the date-grouped
Markdown summary under the shared `"AI Summaries"` Digest category (`SummaryGroup`) via
`supernote.server.components.summary.service.SummaryService`.
See `supernote.guides.mcp` and `supernote.guides.summary_api`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import delete, select

from supernote.models.base import TaskType
from supernote.models.summary import (
    METADATA_CHUNKS,
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
    SummaryItem,
    UpdateSummaryDTO,
)
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import format_summary_prompt
from supernote.server.components.ai import SUMMARY_MODEL_KEY
from supernote.server.components.processor import (
    ProcessorModule,
    ProcessorRegistrar,
    TaskScope,
)
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import SummaryDeletedEvent
from supernote.server.services.file import FileService
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_keywords_map,
    infer_page_date,
)
from supernote.server.utils.paths import (
    AI_SUMMARIES_GROUP_NAME,
    flatten_vfs_path,
    get_ai_summaries_group_id,
    get_summary_id,
)

from . import SUMMARY_CONFIG_KEY
from .chunking import (
    FormattedPage,
    PageChunk,
    compute_chunk_hash,
    format_prior_context,
    merge_chunk_segments,
    normalize_segments,
    parse_cached_chunks,
    partition_pages,
    render_segments_markdown,
)
from .config import SummaryConfig
from .service import SUMMARY_SERVICE_KEY, SummaryService

__all__ = [
    "SummaryModule",
    "async_setup_processor",
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
        config: SummaryConfig | None = None,
    ) -> None:
        self.file_service = file_service
        self.summary_service = summary_service
        self.summary_model = summary_model
        self.config = config if config is not None else SummaryConfig()
        self._group_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "SummaryModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.SUMMARY_GENERATION

    @property
    def scope(self) -> TaskScope:
        return TaskScope.FILE

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return (TaskType.OCR_EXTRACTION,)

    @property
    def enabled(self) -> bool:
        return self.summary_model is not None

    @property
    def supports_standalone_images(self) -> bool:
        return False

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        """Determines if summary generation is needed."""
        # Summary is a file-level task (global), not page-level.
        if page_index is not None:
            return False

        if not await super().run_if_needed(
            file_id, session_manager, page_index, user_id=user_id
        ):
            return False

        async with session_manager.session() as session:
            file_name = (
                await session.execute(
                    select(UserFileDO.file_name).where(UserFileDO.id == file_id)
                )
            ).scalar_one_or_none()
            if not file_name or not file_name.lower().endswith(".note"):
                return False

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

        # Format transcript pages with Page markers and inferred dates
        formatted_pages: list[FormattedPage] = []
        for p in pages:
            if not p.is_blank:
                page_id_str = p.page_id or ""
                metadata = format_page_metadata(
                    page_index=p.page_index,
                    page_id=page_id_str,
                    file_name=file_do.file_name,
                    notebook_create_time=file_do.create_time,
                    keywords=keywords_map.get(page_id_str),
                    include_section_divider=True,
                )
                inferred = infer_page_date(page_id_str)
                formatted_pages.append(
                    FormattedPage(
                        page_index=int(p.page_index),
                        page_id=page_id_str,
                        page_date=inferred.strftime("%Y-%m-%d") if inferred else None,
                        formatted_text=f"{metadata}\n{p.text_content}",
                    )
                )

        summary_uuid = get_summary_id(user_id, file_id)
        if not formatted_pages:
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
        custom_type = Path(file_do.file_name).stem.lower()

        chunks = partition_pages(
            formatted_pages,
            max_pages_per_chunk=self.config.max_pages_per_chunk,
            max_chars_per_chunk=self.config.max_chars_per_chunk,
        )

        cached_chunks: dict[str, list[dict[str, object]]] = {}
        if self.config.incremental and len(chunks) > 1:
            existing_summary = await self.summary_service.get_summary_by_uuid(
                user_email, summary_uuid
            )
            if existing_summary is not None:
                candidate_cache = parse_cached_chunks(existing_summary.metadata)
                # If every chunk in the chain is already cached, `process()` was
                # explicitly re-triggered (e.g. manual reprocess or prompt edit)
                # without page changes — bypass cache so regeneration actually runs.
                if candidate_cache and not self._all_chunks_cached(
                    chunks,
                    candidate_cache,
                    model_id=self.summary_model.model_id,
                    custom_type=custom_type,
                ):
                    cached_chunks = candidate_cache

        chunk_segment_lists: list[list[dict[str, object]]] = []
        chunk_cache_entries: list[dict[str, object]] = []
        prior_context: str | None = None
        cache_hits = 0

        for chunk in chunks:
            effective_prior = prior_context if self.config.carry_over_context else None
            chunk_hash = compute_chunk_hash(
                chunk,
                model_id=self.summary_model.model_id,
                custom_type=custom_type,
                prior_context=effective_prior,
            )
            if self.config.incremental and chunk_hash in cached_chunks:
                chunk_segments = cached_chunks[chunk_hash]
                cache_hits += 1
            else:
                prompt = format_summary_prompt(
                    chunk.transcript,
                    custom_type=custom_type,
                    prior_context=effective_prior,
                )
                summary_response = await self.summary_model.summarize(prompt)
                chunk_segments = normalize_segments(summary_response.segments)

            chunk_segment_lists.append(chunk_segments)
            chunk_cache_entries.append(
                {
                    "chunk_hash": chunk_hash,
                    "segments": chunk_segments,
                }
            )
            if self.config.carry_over_context and chunk_segments:
                prior_context = format_prior_context(chunk_segments)

        clean_segments = merge_chunk_segments(chunk_segment_lists)
        ai_summary = render_segments_markdown(clean_segments)

        # Construct rich metadata for retrieval and incremental chunk caching
        metadata_str: str | None = None
        if clean_segments:
            meta_obj: dict[str, object] = {
                METADATA_SEGMENTS: clean_segments,
                METADATA_CHUNKS: chunk_cache_entries,
            }
            metadata_str = json.dumps(meta_obj)
            logger.info(
                f"Generated metadata for file {file_id}: "
                f"segments={len(clean_segments)} chunks={len(chunks)} cache_hits={cache_hits}"
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

    def _all_chunks_cached(
        self,
        chunks: list[PageChunk],
        cached_chunks: dict[str, list[dict[str, object]]],
        *,
        model_id: str,
        custom_type: str,
    ) -> bool:
        """Return True if every chunk in `chunks` already exists in `cached_chunks`."""
        prior_context: str | None = None
        for chunk in chunks:
            effective_prior = prior_context if self.config.carry_over_context else None
            chunk_hash = compute_chunk_hash(
                chunk,
                model_id=model_id,
                custom_type=custom_type,
                prior_context=effective_prior,
            )
            if chunk_hash not in cached_chunks:
                return False
            chunk_segments = cached_chunks[chunk_hash]
            if self.config.carry_over_context and chunk_segments:
                prior_context = format_prior_context(chunk_segments)
        return True

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


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register `SummaryModule` with the `"processor"` platform."""
    registrar.register_module(
        SummaryModule(
            file_service=core.file_service,
            summary_service=core.app[SUMMARY_SERVICE_KEY],
            summary_model=core.app.get(SUMMARY_MODEL_KEY),
            config=core.app.get(SUMMARY_CONFIG_KEY),
        )
    )
