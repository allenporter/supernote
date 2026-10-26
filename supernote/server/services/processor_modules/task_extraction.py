"""Processor module for extracting and reconciling handwritten tasks into ScheduleService."""

import logging
import time
from typing import Any

from sqlalchemy import select

from supernote.models.base import TaskType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTaskSyncDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.schedule import ScheduleService
from supernote.server.utils.task_parser import (
    ExtractedPageTask,
    ExtractedTaskState,
    parse_page_tasks,
)

__all__ = [
    "DEFAULT_NOTES_TASK_GROUP_TITLE",
    "TaskExtractionModule",
]

logger = logging.getLogger(__name__)

DEFAULT_NOTES_TASK_GROUP_TITLE = "From Notes"


def _build_link_b64(
    file_path: str,
    file_id: int,
    page: NotePageContentDO,
    task_title: str,
) -> str:
    """Build a Base64-encoded ScheduleTaskLinkDTO deep-link for a notebook page."""
    dto = ScheduleTaskLinkDTO(
        app_name="Note",
        path=file_path,
        page=page.page_index + 1,
        file_id=str(file_id),
        page_id=page.page_id,
        task_title=task_title,
    )
    return dto.to_b64()


class TaskExtractionModule(ProcessorModule):
    """Post-OCR notebook module that reconciles handwritten tasks with ScheduleService."""

    def __init__(
        self,
        file_service: FileService,
        schedule_service: ScheduleService,
        enabled: bool = True,
        default_group_title: str = DEFAULT_NOTES_TASK_GROUP_TITLE,
    ) -> None:
        self.file_service = file_service
        self.schedule_service = schedule_service
        self._enabled = enabled
        self.default_group_title = default_group_title

    @property
    def name(self) -> str:
        return "TaskExtractionModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.TASK_EXTRACTION

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Determines if notebook-level task extraction is needed."""
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
                    f"No pages found for file {file_id}; skipping task extraction"
                )
                return False
            missing_count = sum(1 for text in pages if text is None)
            if missing_count > 0:
                logger.debug(
                    f"OCR prerequisite not met for task extraction of file {file_id} "
                    f"({missing_count}/{len(pages)} pages missing text)"
                )
                return False

        return True

    async def _get_or_create_target_group_id(self, user_id: int) -> str:
        """Return the task_list_id for the 'From Notes' task group, creating it lazily if needed."""
        groups = await self.schedule_service.list_groups(user_id)
        for group in groups:
            if group.title == self.default_group_title:
                return group.task_list_id
        created = await self.schedule_service.create_group(
            user_id=user_id,
            title=self.default_group_title,
        )
        return created.task_list_id

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Reconcile all page transcripts for `file_id` against NoteTaskSyncDO and ScheduleService."""
        logger.info(f"Starting task extraction for file_id={file_id}")

        async with session_manager.session() as session:
            file_do = await session.get(UserFileDO, file_id)
            if not file_do:
                logger.error(f"File {file_id} not found.")
                return
            user_id = file_do.user_id
            file_name = file_do.file_name

            pages_result = await session.execute(
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index.asc())
            )
            pages = list(pages_result.scalars().all())

        if not pages:
            return

        file_path = (
            await self.file_service.get_full_path_by_node(user_id, file_id)
            or f"/Note/{file_name}"
        )

        parsed_pages: list[tuple[NotePageContentDO, list[ExtractedPageTask]]] = [
            (
                page,
                parse_page_tasks(
                    page.text_content,
                    page_id=page.page_id,
                    file_name=file_name,
                ),
            )
            for page in pages
        ]

        now_ms = int(time.time() * 1000)
        target_group_id: str | None = None

        async with session_manager.session() as session:
            existing_sync_rows = (
                (
                    await session.execute(
                        select(NoteTaskSyncDO).where(NoteTaskSyncDO.file_id == file_id)
                    )
                )
                .scalars()
                .all()
            )
            sync_map: dict[tuple[str, str], NoteTaskSyncDO] = {
                (row.page_id, row.normalized_title): row for row in existing_sync_rows
            }

            seen_page_keys: set[tuple[str, str]] = set()
            handled_in_phase1: set[tuple[str, str]] = set()

            # ------------------------------------------------------------------
            # Phase 1: Reconcile existing per-page rows on their own page
            # ------------------------------------------------------------------
            for page, extracted_tasks in parsed_pages:
                for extracted in extracted_tasks:
                    key = (page.page_id, extracted.normalized_title)
                    seen_page_keys.add(key)

                    sync_row = sync_map.get(key)
                    if sync_row is None or sync_row.sync_status == "ERASED":
                        continue

                    # If previously CANCELLED on this page and user rewrote an open task,
                    # let Phase 2 handle it as a fresh appearance.
                    if sync_row.sync_status == "CANCELLED" and extracted.state in (
                        ExtractedTaskState.INCOMPLETE,
                        ExtractedTaskState.MIGRATED_FORWARD,
                        ExtractedTaskState.MIGRATED_SCHEDULED,
                    ):
                        continue

                    handled_in_phase1.add(key)
                    sync_row.page_index = page.page_index
                    sync_row.raw_title = extracted.raw_title

                    # Tombstoned rows (SUPERSEDED, DELETED_REMOTE, CANCELLED) do not touch ScheduleService
                    if sync_row.sync_status in (
                        "SUPERSEDED",
                        "DELETED_REMOTE",
                        "CANCELLED",
                    ):
                        sync_row.last_ocr_state = extracted.state.value
                        sync_row.update_time = now_ms
                        continue

                    # sync_row.sync_status == "ACTIVE"
                    remote_task = (
                        await self.schedule_service.get_task(
                            user_id, sync_row.schedule_task_id
                        )
                        if sync_row.schedule_task_id
                        else None
                    )
                    if remote_task is None:
                        # Tombstone Rule A: Task was deleted digitally in To-Do app / Web UI
                        sync_row.sync_status = "DELETED_REMOTE"
                        sync_row.last_ocr_state = extracted.state.value
                        sync_row.update_time = now_ms
                        continue

                    if extracted.state == ExtractedTaskState.CANCELLED:
                        # Tombstone Rule C: Handwritten strikethrough ("~~• Task~~")
                        if remote_task.status == "needsAction":
                            await self.schedule_service.delete_task(
                                user_id, remote_task.task_id
                            )
                        sync_row.sync_status = "CANCELLED"
                        sync_row.last_ocr_state = ExtractedTaskState.CANCELLED.value
                        sync_row.update_time = now_ms
                        continue

                    # Edge-triggered status and metadata updates on ACTIVE task
                    updates: dict[str, Any] = {}
                    if (
                        extracted.state == ExtractedTaskState.COMPLETED
                        and sync_row.last_ocr_state
                        != ExtractedTaskState.COMPLETED.value
                    ):
                        if remote_task.status != "completed":
                            updates["status"] = "completed"
                            updates["completed_time"] = now_ms
                    elif (
                        extracted.state
                        in (
                            ExtractedTaskState.INCOMPLETE,
                            ExtractedTaskState.MIGRATED_FORWARD,
                            ExtractedTaskState.MIGRATED_SCHEDULED,
                        )
                        and sync_row.last_ocr_state
                        == ExtractedTaskState.COMPLETED.value
                    ):
                        if remote_task.status == "completed":
                            updates["status"] = "needsAction"
                            updates["completed_time"] = 0

                    if remote_task.title != extracted.raw_title:
                        updates["title"] = extracted.raw_title

                    if extracted.detail != sync_row.last_detail:
                        updates["detail"] = extracted.detail or ""
                        sync_row.last_detail = extracted.detail

                    new_importance = "high" if extracted.is_starred else None
                    if new_importance != sync_row.last_importance:
                        updates["importance"] = new_importance
                        sync_row.last_importance = new_importance

                    if extracted.inferred_due_time != sync_row.last_due_time:
                        updates["due_time"] = extracted.inferred_due_time
                        sync_row.last_due_time = extracted.inferred_due_time

                    new_links = _build_link_b64(
                        file_path, file_id, page, extracted.raw_title
                    )
                    if remote_task.links != new_links:
                        updates["links"] = new_links

                    if updates:
                        await self.schedule_service.update_task(
                            user_id, remote_task.task_id, **updates
                        )

                    sync_row.last_ocr_state = extracted.state.value
                    sync_row.update_time = now_ms

            # ------------------------------------------------------------------
            # Phase 2: New page appearances & cross-page migrations
            # ------------------------------------------------------------------
            for page, extracted_tasks in parsed_pages:
                for extracted in extracted_tasks:
                    key = (page.page_id, extracted.normalized_title)
                    if key in handled_in_phase1:
                        continue

                    # Look for an ACTIVE candidate task with the same normalized_title on another page
                    candidates = [
                        c
                        for c in sync_map.values()
                        if c.normalized_title == extracted.normalized_title
                        and c.page_id != page.page_id
                        and c.sync_status == "ACTIVE"
                        and c.schedule_task_id is not None
                    ]
                    candidates.sort(
                        key=lambda c: (
                            0
                            if c.last_ocr_state
                            in (
                                ExtractedTaskState.MIGRATED_FORWARD.value,
                                ExtractedTaskState.MIGRATED_SCHEDULED.value,
                            )
                            else 1,
                            c.page_index,
                        )
                    )

                    claimed_candidate: NoteTaskSyncDO | None = None
                    claimed_remote_task = None
                    for candidate in candidates:
                        assert candidate.schedule_task_id is not None
                        remote = await self.schedule_service.get_task(
                            user_id, candidate.schedule_task_id
                        )
                        if remote is None:
                            candidate.sync_status = "DELETED_REMOTE"
                            candidate.update_time = now_ms
                            continue
                        is_migrated_symbol = candidate.last_ocr_state in (
                            ExtractedTaskState.MIGRATED_FORWARD.value,
                            ExtractedTaskState.MIGRATED_SCHEDULED.value,
                        )
                        if is_migrated_symbol or remote.status == "needsAction":
                            claimed_candidate = candidate
                            claimed_remote_task = remote
                            break

                    if (
                        claimed_candidate is not None
                        and claimed_remote_task is not None
                    ):
                        # Tombstone Rule B: Supersede the earlier page's sync row
                        claimed_candidate.sync_status = "SUPERSEDED"
                        claimed_candidate.update_time = now_ms

                        merged_detail = (
                            extracted.detail
                            if extracted.detail is not None
                            else claimed_candidate.last_detail
                        )
                        merged_importance = (
                            "high"
                            if extracted.is_starred
                            else claimed_candidate.last_importance
                        )
                        merged_due_time = (
                            extracted.inferred_due_time
                            if extracted.inferred_due_time is not None
                            else claimed_candidate.last_due_time
                        )

                        if extracted.state == ExtractedTaskState.CANCELLED:
                            if claimed_remote_task.status == "needsAction":
                                await self.schedule_service.delete_task(
                                    user_id, claimed_remote_task.task_id
                                )
                            new_status = "CANCELLED"
                        else:
                            new_links = _build_link_b64(
                                file_path, file_id, page, extracted.raw_title
                            )
                            mig_updates: dict[str, Any] = {
                                "title": extracted.raw_title,
                                "links": new_links,
                            }
                            if merged_detail != claimed_remote_task.detail:
                                mig_updates["detail"] = merged_detail or ""
                            if merged_importance != claimed_remote_task.importance:
                                mig_updates["importance"] = merged_importance
                            if merged_due_time != claimed_remote_task.due_time:
                                mig_updates["due_time"] = merged_due_time
                            if (
                                extracted.state == ExtractedTaskState.COMPLETED
                                and claimed_remote_task.status != "completed"
                            ):
                                mig_updates["status"] = "completed"
                                mig_updates["completed_time"] = now_ms

                            await self.schedule_service.update_task(
                                user_id,
                                claimed_remote_task.task_id,
                                **mig_updates,
                            )
                            new_status = "ACTIVE"

                        sync_row = sync_map.get(key)
                        if sync_row is None:
                            sync_row = NoteTaskSyncDO(
                                user_id=user_id,
                                file_id=file_id,
                                page_id=page.page_id,
                                page_index=page.page_index,
                                normalized_title=extracted.normalized_title,
                                raw_title=extracted.raw_title,
                                schedule_task_id=claimed_remote_task.task_id,
                                sync_status=new_status,
                                last_ocr_state=extracted.state.value,
                                last_detail=merged_detail,
                                last_importance=merged_importance,
                                last_due_time=merged_due_time,
                                create_time=now_ms,
                                update_time=now_ms,
                            )
                            session.add(sync_row)
                            sync_map[key] = sync_row
                        else:
                            sync_row.page_index = page.page_index
                            sync_row.raw_title = extracted.raw_title
                            sync_row.schedule_task_id = claimed_remote_task.task_id
                            sync_row.sync_status = new_status
                            sync_row.last_ocr_state = extracted.state.value
                            sync_row.last_detail = merged_detail
                            sync_row.last_importance = merged_importance
                            sync_row.last_due_time = merged_due_time
                            sync_row.update_time = now_ms
                        continue

                    # Ignore pre-completed ('X') or pre-cancelled ('~~...~~') items on first sight
                    if extracted.state in (
                        ExtractedTaskState.COMPLETED,
                        ExtractedTaskState.CANCELLED,
                    ):
                        continue

                    # Create brand-new task in ScheduleService
                    if target_group_id is None:
                        target_group_id = await self._get_or_create_target_group_id(
                            user_id
                        )

                    importance = "high" if extracted.is_starred else None
                    links_b64 = _build_link_b64(
                        file_path, file_id, page, extracted.raw_title
                    )
                    created_task = await self.schedule_service.create_task(
                        user_id=user_id,
                        group_id=target_group_id,
                        title=extracted.raw_title,
                        detail=extracted.detail or "",
                        status="needsAction",
                        importance=importance,
                        due_time=extracted.inferred_due_time,
                        links=links_b64,
                    )

                    sync_row = sync_map.get(key)
                    if sync_row is None:
                        sync_row = NoteTaskSyncDO(
                            user_id=user_id,
                            file_id=file_id,
                            page_id=page.page_id,
                            page_index=page.page_index,
                            normalized_title=extracted.normalized_title,
                            raw_title=extracted.raw_title,
                            schedule_task_id=created_task.task_id,
                            sync_status="ACTIVE",
                            last_ocr_state=extracted.state.value,
                            last_detail=extracted.detail,
                            last_importance=importance,
                            last_due_time=extracted.inferred_due_time,
                            create_time=now_ms,
                            update_time=now_ms,
                        )
                        session.add(sync_row)
                        sync_map[key] = sync_row
                    else:
                        sync_row.page_index = page.page_index
                        sync_row.raw_title = extracted.raw_title
                        sync_row.schedule_task_id = created_task.task_id
                        sync_row.sync_status = "ACTIVE"
                        sync_row.last_ocr_state = extracted.state.value
                        sync_row.last_detail = extracted.detail
                        sync_row.last_importance = importance
                        sync_row.last_due_time = extracted.inferred_due_time
                        sync_row.update_time = now_ms

            # ------------------------------------------------------------------
            # Phase 3: Clean up ACTIVE tasks that were erased from their page
            # (or whose page was deleted) without being migrated to another page
            # ------------------------------------------------------------------
            for key, sync_row in list(sync_map.items()):
                if sync_row.sync_status == "ACTIVE" and key not in seen_page_keys:
                    if sync_row.schedule_task_id:
                        remote_task = await self.schedule_service.get_task(
                            user_id, sync_row.schedule_task_id
                        )
                        if (
                            remote_task is not None
                            and remote_task.status == "needsAction"
                        ):
                            await self.schedule_service.delete_task(
                                user_id, remote_task.task_id
                            )
                    sync_row.sync_status = "ERASED"
                    sync_row.update_time = now_ms

            await session.commit()
