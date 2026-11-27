"""Stage 1 of the `.note` processing pipeline: page-level change detection (`TaskType.PAGE_HASHING`).

`PageHashingModule` parses binary `.note` metadata via `supernote.notebook.parser.parse_metadata`,
computes an MD5 digest per page (`PAGEID`), and reconciles
`supernote.server.db.models.note_processing.NotePageContentDO` rows. When a page is
added, modified, moved, or deleted, downstream per-page task checkpoints (`SystemTaskDO`)
and file-level post-processing checkpoints are selectively invalidated so unchanged pages
are never re-rendered or re-transcribed.
See `supernote.guides.note_processing_design`.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from supernote.models.base import TaskType
from supernote.notebook import parse_metadata
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NotePagesDeltaEvent
from supernote.server.metrics import record_note_page_diff
from supernote.server.services.file import FileService
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.image import STANDALONE_IMAGE_PAGE_ID, is_image_filename
from supernote.server.utils.paths import get_page_png_path, is_valid_page_id

from .base import ProcessorModule, TaskScope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PageDiffCounts:
    """Mutually exclusive reconciliation counts across pages in a `.note` run."""

    added: int = 0
    modified: int = 0
    moved: int = 0
    unchanged: int = 0
    deleted: int = 0
    added_pages: tuple[str, ...] = ()
    modified_pages: tuple[str, ...] = ()
    moved_pages: tuple[str, ...] = ()
    deleted_pages: tuple[str, ...] = ()
    deleted_page_texts: tuple[tuple[str, str], ...] = ()


def _extract_page_identities(path: str) -> list[tuple[str, str]]:
    """Parse `.note` metadata once and return `(page_id, content_hash)` per page."""
    page_identities: list[tuple[str, str]] = []
    with open(path, "rb") as stream:
        metadata = parse_metadata(stream, policy="loose")
        for page_info in metadata.pages:
            raw_pid = page_info.page_id
            page_id = (
                raw_pid
                if isinstance(raw_pid, str) and is_valid_page_id(raw_pid)
                else ""
            )
            content_hash = get_md5_hash(str(page_info.to_wire_dict()))
            page_identities.append((page_id, content_hash))
    return page_identities


class PageHashingModule(ProcessorModule):
    """Global pre-processor that extracts page identities and reconciles page hashes.

    Responsibilities:
    - Parses `.note` metadata via `parse_metadata()` without loading bitmaps.
    - Reconciles `NotePageContentDO` rows by `<PAGEID>` and invalidates downstream
      `SystemTaskDO` checkpoints for modified or deleted pages.
    - Publishes `NotePagesDeltaEvent` when pages are added, modified, moved, or deleted.
    """

    def __init__(self, file_service: FileService) -> None:
        self.file_service = file_service

    @property
    def name(self) -> str:
        return "PageHashingModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.PAGE_HASHING

    @property
    def scope(self) -> TaskScope:
        return TaskScope.FILE

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return ()

    @property
    def version(self) -> str:
        """Module schema version recorded in `SystemTaskDO.data`."""
        return "v3"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        """Hashing acts as the change detector, so it runs whenever the file is active in DB."""
        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO.storage_key).where(
                    UserFileDO.id == file_id,
                    UserFileDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                )
            )
            storage_key = result.scalar_one_or_none()
        if not storage_key:
            logger.warning(
                f"Skipping PageHashingModule for file_id={file_id}: "
                "active file with storage_key not found"
            )
            return False
        return True

    async def _delete_cache_blob(self, key: str) -> None:
        try:
            await self.file_service.blob_storage.delete(CACHE_BUCKET, key)
        except OSError as e:
            logger.warning(f"Failed to delete cache blob {key}: {e}")

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Parse `.note` page identities and reconcile `NotePageContentDO` checkpoints."""
        logger.info(f"Starting PageHashingModule for file_id={file_id}")

        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file:
                logger.error(f"File {file_id} not found in DB")
                return

            user_id = user_file.user_id
            file_name = user_file.file_name
            file_md5 = user_file.md5
            storage_key = user_file.storage_key
            if not storage_key:
                logger.error(f"File {file_id} has no storage_key")
                return

            if is_image_filename(file_name):
                content_hash = file_md5 or storage_key
                content_diff = await self._sync_page_content_hashes(
                    session,
                    user_id=user_id,
                    file_id=file_id,
                    page_identities=[(STANDALONE_IMAGE_PAGE_ID, content_hash)],
                )
                await session.commit()
                record_note_page_diff(
                    added=content_diff.added,
                    modified=content_diff.modified,
                    moved=content_diff.moved,
                    unchanged=content_diff.unchanged,
                    deleted=content_diff.deleted,
                )
                logger.info(
                    f"Completed PageHashingModule for standalone image file_id={file_id}"
                )
                return

        abs_path = self.file_service.blob_storage.get_blob_path(
            USER_DATA_BUCKET, storage_key
        )
        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            raise FileNotFoundError(f"File {abs_path} does not exist on disk")

        loop = asyncio.get_running_loop()
        page_identities = await loop.run_in_executor(
            None,
            partial(_extract_page_identities, str(abs_path)),
        )

        async with session_manager.session() as session:
            content_diff = await self._sync_page_content_hashes(
                session,
                user_id=user_id,
                file_id=file_id,
                page_identities=page_identities,
            )
            await session.commit()

        record_note_page_diff(
            added=content_diff.added,
            modified=content_diff.modified,
            moved=content_diff.moved,
            unchanged=content_diff.unchanged,
            deleted=content_diff.deleted,
        )

        if self.file_service.event_bus and (
            content_diff.added_pages
            or content_diff.modified_pages
            or content_diff.moved_pages
            or content_diff.deleted_pages
        ):
            file_path = await self.file_service.get_full_path_by_node(user_id, file_id)
            await self.file_service.event_bus.publish(
                NotePagesDeltaEvent(
                    user_id=user_id,
                    file_id=file_id,
                    file_path=file_path,
                    added_pages=list(content_diff.added_pages),
                    modified_pages=list(content_diff.modified_pages),
                    moved_pages=list(content_diff.moved_pages),
                    deleted_pages=list(content_diff.deleted_pages),
                    deleted_page_texts=dict(content_diff.deleted_page_texts),
                )
            )

    async def _sync_page_content_hashes(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        file_id: int,
        page_identities: Sequence[tuple[str, str]],
    ) -> _PageDiffCounts:
        """Reconcile `NotePageContentDO` rows by `<PAGEID>` and invalidate stale checkpoints."""
        existing_pages = await session.execute(
            select(NotePageContentDO)
            .options(undefer(NotePageContentDO.previous_text))
            .where(NotePageContentDO.file_id == file_id)
        )
        existing_map = {p.page_id: p for p in existing_pages.scalars().all()}

        current_page_ids: set[str] = set()
        any_page_changed = False
        added = 0
        modified = 0
        moved = 0
        unchanged = 0
        deleted = 0
        added_pages: list[str] = []
        modified_pages: list[str] = []
        moved_pages: list[str] = []
        deleted_pages: list[str] = []
        deleted_page_texts: list[tuple[str, str]] = []

        for i, (page_id, current_hash) in enumerate(page_identities):
            if not page_id:
                logger.warning(
                    f"Page {i} of file {file_id} has missing or invalid PAGEID."
                )
                continue

            current_page_ids.add(page_id)

            if page_id in existing_map:
                row = existing_map[page_id]
                index_changed = row.page_index != i
                hash_changed = row.content_hash != current_hash

                if index_changed:
                    logger.info(f"Page {page_id} moved from {row.page_index} to {i}")
                    row.page_index = i
                    any_page_changed = True

                if hash_changed:
                    logger.info(f"Page {page_id} (idx {i}) changed. Resetting content.")
                    row.content_hash = current_hash
                    if row.text_content is not None:
                        row.previous_text = row.text_content or None
                    row.text_content = None
                    row.embedding = None
                    row.embedding_model = None
                    any_page_changed = True
                    modified += 1
                    modified_pages.append(page_id)

                    page_task_key = f"page_{page_id}"
                    await session.execute(
                        delete(SystemTaskDO)
                        .where(SystemTaskDO.user_id == user_id)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.key == page_task_key)
                    )
                elif index_changed:
                    moved += 1
                    moved_pages.append(page_id)
                else:
                    unchanged += 1
            else:
                logger.info(f"New page {page_id} at index {i} detected.")
                any_page_changed = True
                added += 1
                added_pages.append(page_id)
                session.add(
                    NotePageContentDO(
                        file_id=file_id,
                        page_index=i,
                        page_id=page_id,
                        content_hash=current_hash,
                        text_content=None,
                        embedding=None,
                        embedding_model=None,
                    )
                )

        for pid, row in existing_map.items():
            if pid not in current_page_ids:
                logger.info(f"Page {pid} deleted (was at {row.page_index}).")
                any_page_changed = True
                deleted += 1
                deleted_pages.append(pid)
                last_text = (
                    row.text_content
                    if row.text_content is not None
                    else row.previous_text
                )
                if last_text:
                    deleted_page_texts.append((pid, last_text))
                await session.delete(row)

                await self._delete_cache_blob(get_page_png_path(file_id, pid))

                await session.execute(
                    delete(SystemTaskDO)
                    .where(SystemTaskDO.user_id == user_id)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.key == f"page_{pid}")
                )

        if any_page_changed:
            await session.execute(
                delete(SystemTaskDO)
                .where(SystemTaskDO.user_id == user_id)
                .where(SystemTaskDO.file_id == file_id)
                .where(SystemTaskDO.key == "global")
                .where(SystemTaskDO.task_type != TaskType.PAGE_HASHING.value)
            )

        return _PageDiffCounts(
            added=added,
            modified=modified,
            moved=moved,
            unchanged=unchanged,
            deleted=deleted,
            added_pages=tuple(added_pages),
            modified_pages=tuple(modified_pages),
            moved_pages=tuple(moved_pages),
            deleted_pages=tuple(deleted_pages),
            deleted_page_texts=tuple(deleted_page_texts),
        )
