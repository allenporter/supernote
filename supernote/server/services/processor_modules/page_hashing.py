import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import TaskType
from supernote.notebook import Notebook, Page, load, parse_metadata
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.metrics import record_note_page_diff
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.paths import get_page_png_path, is_valid_page_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PageDiffCounts:
    """Mutually exclusive reconciliation counts across pages in a `.note` run."""

    added: int = 0
    modified: int = 0
    moved: int = 0
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


class PageHashingModule(ProcessorModule):
    """Global pre-processor that extracts `.note` metadata and reconciles page hashes.

    Responsibilities:
    - Parses `.note` metadata via `parse_metadata()` and calls
      `load(stream, metadata=metadata, page_number=i)` only for pages whose
      `content_hash` is not already cached.
    - Persists `NoteMetadataDO` and changed `NotePageMetadataDO` rows (`0..total_pages - 1`).
    - Reconciles `NotePageContentDO` rows by `<PAGEID>` and invalidates downstream
      `SystemTaskDO` checkpoints for modified or deleted pages.
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
    def version(self) -> str:
        """Module schema version recorded in `SystemTaskDO.data`.

        Bumping to `v2` causes `ProcessorService.recover_missing_tasks()` to
        re-run `PageHashingModule` on previously hashed `.note` files so
        `f_note_metadata` and `f_note_page_metadata` are backfilled automatically.
        """
        return "v2"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Hashing acts as the change detector, so it MUST run every time the file is processed."""
        return True

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete persisted notebook and page metadata rows for a deleted note."""
        async with session_manager.session() as session:
            await session.execute(
                delete(NoteMetadataDO).where(NoteMetadataDO.file_id == file_id)
            )
            await session.execute(
                delete(NotePageMetadataDO).where(NotePageMetadataDO.file_id == file_id)
            )
            await session.commit()

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Parse `.note` metadata, scan uncached page ink, and reconcile DB checkpoints."""
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
            storage_key = user_file.storage_key
            if not storage_key:
                logger.error(f"File {file_id} has no storage_key")
                return

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
            content_diff = await self._sync_page_content_hashes(
                session, file_id=file_id, page_identities=page_identities
            )
            await session.commit()

        record_note_page_diff(
            added=legacy_diff.added + content_diff.added,
            modified=legacy_diff.modified + content_diff.modified,
            moved=legacy_diff.moved + content_diff.moved,
            unchanged=legacy_diff.unchanged + content_diff.unchanged,
            deleted=legacy_diff.deleted + content_diff.deleted,
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
    ) -> _PageDiffCounts:
        """Synchronize notebook-level and per-page metadata rows with the parsed `.note` file.

        `NoteMetadataDO` is upserted once per file with container fields and lossless
        header/footer wire JSON. `NotePageMetadataDO` is reconciled by 0-based `page_index`
        (rather than `page_id`, unlike `NotePageContentDO`) so every page—including legacy
        notes lacking `<PAGEID>`—has an ordered row, unchanged pages avoid redundant SQL
        `UPDATE`s, and trailing rows left over when a notebook shrinks are deleted.
        """
        metadata = notebook.metadata
        legacy_added = 0
        legacy_modified = 0
        legacy_unchanged = 0
        legacy_deleted = 0

        # Upsert notebook-level container fields and raw header/footer wire dicts.
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

        # Index existing page metadata by 0-based slot; popping each current index
        # leaves any truncated tail pages (>= total_pages) behind for deletion.
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
            # Keywords, titles, and links live in the notebook footer rather than the
            # page's own metadata block, so check both content_hash and serialized
            # annotations before skipping to avoid mutating clean ORM rows (and bumping update_time).
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

            # `notebook` was constructed from metadata without loading bitmaps, so combine
            # the cached/scanned `page_has_ink[i]` flag with metadata-level drawable flags.
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

        return _PageDiffCounts(
            added=legacy_added,
            modified=legacy_modified,
            unchanged=legacy_unchanged,
            deleted=legacy_deleted,
        )

    async def _sync_page_content_hashes(
        self,
        session: AsyncSession,
        *,
        file_id: int,
        page_identities: Sequence[tuple[str, str]],
    ) -> _PageDiffCounts:
        """Reconcile `NotePageContentDO` rows by `<PAGEID>` and invalidate stale checkpoints."""
        existing_pages = await session.execute(
            select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
        )
        existing_map = {p.page_id: p for p in existing_pages.scalars().all()}

        current_page_ids: set[str] = set()
        any_page_changed = False
        added = 0
        modified = 0
        moved = 0
        unchanged = 0
        deleted = 0

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
                    row.text_content = None
                    row.embedding = None
                    row.embedding_model = None
                    any_page_changed = True
                    modified += 1

                    # SystemTaskDO rows act as completion checkpoints; deleting
                    # the page's task rows causes downstream page modules (PNG,
                    # OCR, Embedding) to see no COMPLETED record in run_if_needed()
                    # and re-process this page.
                    page_task_key = f"page_{page_id}"
                    await session.execute(
                        delete(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.key == page_task_key)
                    )
                elif index_changed:
                    moved += 1
                else:
                    unchanged += 1
            else:
                logger.info(f"New page {page_id} at index {i} detected.")
                any_page_changed = True
                added += 1
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
                await session.delete(row)

                png_path = get_page_png_path(file_id, pid)
                try:
                    await self.file_service.blob_storage.delete(CACHE_BUCKET, png_path)
                except (FileNotFoundError, OSError) as e:
                    logger.warning(f"Failed to delete orphan PNG {pid}: {e}")

                await session.execute(
                    delete(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.key == f"page_{pid}")
                )

        if any_page_changed:
            # Delete COMPLETED global post-processing checkpoints so file-level
            # modules re-run during the global post-processing stage (and during
            # missing-task recovery if interrupted) without PageHashingModule
            # knowing which downstream modules exist.
            await session.execute(
                delete(SystemTaskDO)
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
        )
