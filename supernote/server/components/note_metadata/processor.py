"""Processor platform stage extracting structural `.note` metadata (`TaskType.NOTE_METADATA`).

`NoteMetadataModule` parses binary `.note` headers, footers, per-page metadata,
ink/drawable flags, keywords, links, and native titles into `NoteMetadataDO`,
`NotePageMetadataDO`, and `NoteTitleDO`. Unchanged pages skip layer bitmap ink
decoding via cached `NotePageMetadataDO.content_hash` digests, and title
transcriptions follow their handwriting across slots via `bitmap_md5`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import TaskType
from supernote.notebook import Notebook, Page, Title, load, parse_metadata
from supernote.notebook.parser import load_title_bitmaps
from supernote.server.components.processor import (
    ProcessorModule,
    ProcessorRegistrar,
    TaskScope,
)
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageMetadataDO,
    NoteTitleDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.metrics import record_note_page_diff
from supernote.server.services.file import FileService
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.image import is_image_filename
from supernote.server.utils.paths import (
    get_title_png_path,
    get_title_png_prefix,
    is_valid_page_id,
)

__all__ = [
    "NoteMetadataModule",
    "async_setup_processor",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LegacyPageDiffCounts:
    """Reconciliation counts for legacy `.note` pages that lack `<PAGEID>`."""

    added: int = 0
    modified: int = 0
    unchanged: int = 0
    deleted: int = 0


def _serialize_page_annotations(page_obj: Page) -> tuple[str, str, str]:
    """Serialize footer-anchored keywords, titles, and links for a page."""
    keywords_json = json.dumps(
        [kw.metadata.to_wire_dict() for kw in page_obj.keywords],
        ensure_ascii=False,
    )
    titles_json = json.dumps(
        [t.metadata.to_wire_dict() for t in page_obj.titles],
        ensure_ascii=False,
    )
    links_json = json.dumps(
        [lk.metadata.to_wire_dict() for lk in page_obj.links],
        ensure_ascii=False,
    )
    return keywords_json, titles_json, links_json


def _title_reading_order(title: Title) -> tuple[int, int, int]:
    """Sort key placing titles by page, then top-to-bottom, then left-to-right."""
    rect = title.metadata.rect
    if rect is None:
        return (title.page_number, 0, 0)
    return (title.page_number, rect.top, rect.left)


def _load_incremental_notebook(
    path: str,
    cached_ink: dict[str, bool],
) -> tuple[Notebook, list[tuple[str, str]], list[bool]]:
    """Parse `.note` metadata once and call `load(stream, ..., page_number=i)` only for uncached page hashes."""
    page_identities: list[tuple[str, str]] = []
    page_has_ink: list[bool] = []

    with open(path, "rb") as stream:
        metadata = parse_metadata(stream, policy="loose")
        notebook = Notebook(metadata)
        # Title bitmaps are a few KB each; hashing them lets transcribed title
        # text be matched to its handwriting across passes (see `_sync_titles`).
        load_title_bitmaps(stream, notebook.titles)

        for i, page_info in enumerate(metadata.pages):
            raw_pid = page_info.page_id
            page_id = (
                raw_pid
                if isinstance(raw_pid, str) and is_valid_page_id(raw_pid)
                else ""
            )
            content_hash = get_md5_hash(str(page_info.to_wire_dict()))
            page_identities.append((page_id, content_hash))

            if content_hash in cached_ink:
                page_has_ink.append(cached_ink[content_hash])
            else:
                loaded_nb = load(
                    stream, metadata=metadata, policy="loose", page_number=i
                )
                page_has_ink.append(loaded_nb.page(i).has_ink)

    return notebook, page_identities, page_has_ink


class NoteMetadataModule(ProcessorModule):
    """File-scoped stage extracting `.note` header, footer, page metadata, and titles."""

    def __init__(self, file_service: FileService) -> None:
        self.file_service = file_service

    @property
    def name(self) -> str:
        return "NoteMetadataModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.NOTE_METADATA

    @property
    def scope(self) -> TaskScope:
        return TaskScope.FILE

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return (TaskType.PAGE_HASHING,)

    @property
    def supports_standalone_images(self) -> bool:
        return False

    @property
    def version(self) -> str:
        """Module schema version recorded in `SystemTaskDO.data`."""
        return "v1"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        """Run on every active `.note` sync so footer-only edits (titles, keywords, links) are captured."""
        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO.storage_key, UserFileDO.file_name).where(
                    UserFileDO.id == file_id,
                    UserFileDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                )
            )
            row = result.one_or_none()
        if row is None or not row.storage_key or is_image_filename(row.file_name):
            return False
        return True

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete persisted notebook/page/title metadata rows and cached title crops."""
        async with session_manager.session() as session:
            await session.execute(
                delete(NoteMetadataDO).where(
                    NoteMetadataDO.user_id == user_id,
                    NoteMetadataDO.file_id == file_id,
                )
            )
            await session.execute(
                delete(NotePageMetadataDO).where(
                    NotePageMetadataDO.user_id == user_id,
                    NotePageMetadataDO.file_id == file_id,
                )
            )
            await session.execute(
                delete(NoteTitleDO).where(
                    NoteTitleDO.user_id == user_id, NoteTitleDO.file_id == file_id
                )
            )
            await session.commit()
        blob_storage = self.file_service.blob_storage
        for key in await blob_storage.list_blobs(
            CACHE_BUCKET, get_title_png_prefix(file_id)
        ):
            await self._delete_cache_blob(key)

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
        """Parse `.note` structure, scan uncached page ink, and reconcile metadata and title rows."""
        logger.info(f"Starting NoteMetadataModule for file_id={file_id}")

        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file or not user_file.storage_key:
                logger.error(f"File {file_id} not found or missing storage_key")
                return
            if is_image_filename(user_file.file_name):
                return

            user_id = user_file.user_id
            storage_key = user_file.storage_key

            cached_rows = (
                await session.execute(
                    select(
                        NotePageMetadataDO.content_hash,
                        NotePageMetadataDO.has_ink,
                    ).where(
                        NotePageMetadataDO.user_id == user_id,
                        NotePageMetadataDO.file_id == file_id,
                    )
                )
            ).all()
            cached_ink = {
                row.content_hash: row.has_ink for row in cached_rows if row.content_hash
            }

        abs_path = self.file_service.blob_storage.get_blob_path(
            USER_DATA_BUCKET, storage_key
        )
        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            raise FileNotFoundError(f"File {abs_path} does not exist on disk")

        loop = asyncio.get_running_loop()
        notebook, page_identities, page_has_ink = await loop.run_in_executor(
            None,
            partial(_load_incremental_notebook, str(abs_path), cached_ink),
        )

        async with session_manager.session() as session:
            legacy_diff = await self._sync_note_and_page_metadata(
                session,
                user_id=user_id,
                file_id=file_id,
                notebook=notebook,
                page_identities=page_identities,
                page_has_ink=page_has_ink,
            )
            await self._sync_titles(
                session, user_id=user_id, file_id=file_id, notebook=notebook
            )
            await session.commit()

        if (
            legacy_diff.added
            or legacy_diff.modified
            or legacy_diff.unchanged
            or legacy_diff.deleted
        ):
            record_note_page_diff(
                added=legacy_diff.added,
                modified=legacy_diff.modified,
                moved=0,
                unchanged=legacy_diff.unchanged,
                deleted=legacy_diff.deleted,
            )

    async def _sync_note_and_page_metadata(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        file_id: int,
        notebook: Notebook,
        page_identities: Sequence[tuple[str, str]],
        page_has_ink: Sequence[bool],
    ) -> _LegacyPageDiffCounts:
        """Synchronize notebook-level and per-page metadata rows with the parsed `.note` file."""
        metadata = notebook.metadata
        legacy_added = 0
        legacy_modified = 0
        legacy_unchanged = 0
        legacy_deleted = 0

        meta_do = await session.get(NoteMetadataDO, (user_id, file_id))
        if meta_do is None:
            meta_do = NoteMetadataDO(user_id=user_id, file_id=file_id)
            session.add(meta_do)

        meta_do.native_file_id = notebook.file_id
        meta_do.file_type = notebook.type
        meta_do.signature = notebook.signature
        meta_do.total_pages = notebook.total_pages
        meta_do.header_json = json.dumps(
            metadata.header.to_wire_dict(), ensure_ascii=False
        )
        meta_do.footer_json = json.dumps(
            metadata.footer.to_wire_dict(), ensure_ascii=False
        )

        existing_page_meta_res = await session.execute(
            select(NotePageMetadataDO).where(
                NotePageMetadataDO.user_id == user_id,
                NotePageMetadataDO.file_id == file_id,
            )
        )
        existing_page_meta = {
            pm.page_index: pm for pm in existing_page_meta_res.scalars().all()
        }

        for i, (page_id, content_hash) in enumerate(page_identities):
            pm = existing_page_meta.pop(i, None)
            if not page_id:
                if pm is None:
                    legacy_added += 1
                elif pm.content_hash != content_hash:
                    legacy_modified += 1
                else:
                    legacy_unchanged += 1

            page_obj = notebook.pages[i]
            keywords_json, titles_json, links_json = _serialize_page_annotations(
                page_obj
            )
            if (
                pm is not None
                and pm.page_id == page_id
                and pm.content_hash == content_hash
                and pm.keywords_json == keywords_json
                and pm.titles_json == titles_json
                and pm.links_json == links_json
            ):
                continue

            if pm is None:
                pm = NotePageMetadataDO(
                    user_id=user_id,
                    file_id=file_id,
                    page_index=i,
                )
                session.add(pm)

            has_ink = page_has_ink[i]
            pm.page_id = page_id
            pm.content_hash = content_hash
            pm.page_style = page_obj.style
            pm.has_ink = has_ink
            pm.has_drawables = (
                has_ink or page_obj.has_textbox or page_obj.has_vector_graph
            )
            pm.page_json = json.dumps(
                page_obj.metadata.to_wire_dict(), ensure_ascii=False
            )
            pm.keywords_json = keywords_json
            pm.titles_json = titles_json
            pm.links_json = links_json

        for stale_pm in existing_page_meta.values():
            if not stale_pm.page_id:
                legacy_deleted += 1
            await session.delete(stale_pm)

        return _LegacyPageDiffCounts(
            added=legacy_added,
            modified=legacy_modified,
            unchanged=legacy_unchanged,
            deleted=legacy_deleted,
        )

    async def _sync_titles(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        file_id: int,
        notebook: Notebook,
    ) -> None:
        """Reconcile `NoteTitleDO` rows with the notebook's titles in reading order."""
        existing = {
            row.title_index: row
            for row in (
                await session.execute(
                    select(NoteTitleDO)
                    .where(
                        NoteTitleDO.user_id == user_id,
                        NoteTitleDO.file_id == file_id,
                    )
                    .order_by(NoteTitleDO.title_index)
                )
            ).scalars()
        }
        previous_md5s = {row.bitmap_md5 for row in existing.values() if row.bitmap_md5}
        current_md5s: set[str] = set()

        for idx, title in enumerate(sorted(notebook.titles, key=_title_reading_order)):
            row = existing.pop(idx, None)
            if row is None:
                row = NoteTitleDO(user_id=user_id, file_id=file_id, title_index=idx)
                session.add(row)
            rect = title.metadata.rect
            bitmap_md5 = (
                hashlib.md5(title.content).hexdigest() if title.content else None
            )
            row.page_index = title.page_number
            row.rect_left = rect.left if rect else None
            row.rect_top = rect.top if rect else None
            row.rect_width = rect.width if rect else None
            row.rect_height = rect.height if rect else None
            row.level = title.heading_level
            row.style = title.style
            row.bitmap_md5 = bitmap_md5
            if bitmap_md5:
                current_md5s.add(bitmap_md5)

        for stale in existing.values():
            await session.delete(stale)

        # Title crops are cached by bitmap MD5; drop crops for handwriting that
        # no longer appears in the note (redrawn or deleted titles). Deleting
        # before the caller commits is safe: a rollback keeps the rows and the
        # crop is simply re-rendered on its next request.
        for stale_md5 in previous_md5s - current_md5s:
            await self._delete_cache_blob(get_title_png_path(file_id, stale_md5))


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register `NoteMetadataModule` on the processor platform."""
    registrar.register_module(NoteMetadataModule(file_service=core.file_service))
