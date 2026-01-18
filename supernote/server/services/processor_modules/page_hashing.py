import asyncio
import logging
from functools import partial
from typing import Any, Optional

from sqlalchemy import delete, select

from supernote.notebook.parser import parse_metadata
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


def _parse_helper(path: str) -> Any:
    with open(path, "rb") as f:
        return parse_metadata(f)  # type: ignore[arg-type]


class PageHashingModule(ProcessorModule):
    """Module responsible for detecting changes in .note files at the page level.

    This module performs the following:
    - Parses the binary .note file using `SupernoteParser`.
    - Computes a unique MD5 hash for each page based on its layer metadata.
    - Updates the `NotePageContentDO` table:
        - Creates entries for new pages.
        - Updates hashes for changed pages and invalidates downstream data (OCR, Embeddings) to trigger reprocessing.
        - Removes entries for deleted pages.
    - Updates the `SystemTaskDO` status for the 'HASHING' task (handled by base class).

    This module acts as the entry point and "change detector" for the incremental processing pipeline.
    """

    def __init__(self, file_service: FileService) -> None:
        self.file_service = file_service

    @property
    def name(self) -> str:
        return "PageHashingModule"

    @property
    def task_type(self) -> str:
        return "HASHING"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> bool:
        """Hashing acts as the change detector, so it MUST run every time the file is processed."""
        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        """Parses the .note file, computes page hashes, and updates NotePageContentDO."""
        logger.info(f"Starting PageHashingModule for file_id={file_id}")

        # Resolve file path
        async with session_manager.session() as session:
            # Get UserFileDO to find owner & storage key
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file:
                logger.error(f"File {file_id} not found in DB")
                return

            storage_key = user_file.storage_key
            if not storage_key:
                logger.error(f"File {file_id} has no storage_key")
                return

        # Construct real OS path via BlobStorage (No DB access needed here)
        try:
            # This assumes LocalBlobStorage. For S3, we'd need to stream,
            # but SupernoteParser currently expects a file path.
            abs_path = self.file_service.blob_storage.get_blob_path(
                USER_DATA_BUCKET, storage_key
            )
        except Exception as e:
            logger.error(f"Failed to resolve blob path for {file_id}: {e}")
            return

        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            return

        # Parse .note file
        try:
            # Run parser in thread pool
            loop = asyncio.get_running_loop()
            metadata = await loop.run_in_executor(
                None, partial(_parse_helper, str(abs_path))
            )

        except Exception as e:
            logger.error(f"Failed to parse .note file {file_id}: {e}")
            return

        # Iterate pages and update DB
        total_pages = metadata.get_total_pages()
        if not metadata.pages:
            return

        async with session_manager.session() as session:
            # 1. Fetch all existing pages for this file and map by page_id
            existing_pages = await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
            existing_map = {p.page_id: p for p in existing_pages.scalars().all()}

            # Track which page_ids are present in the current file
            current_page_ids = set()

            for i in range(total_pages):
                page_info = metadata.pages[i]
                page_id = page_info.get("PAGEID")

                if not page_id:
                    logger.warning(f"Page {i} of file {file_id} has no PAGEID.")
                    continue

                current_page_ids.add(page_id)

                # Canonical string representation of page metadata for hashing
                page_hash_input = str(page_info)
                current_hash = get_md5_hash(page_hash_input)

                if page_id in existing_map:
                    # UPDATE path
                    row = existing_map[page_id]

                    # Check for Move (Index Changed)
                    if row.page_index != i:
                        logger.info(
                            f"Page {page_id} moved from {row.page_index} to {i}"
                        )
                        row.page_index = i

                    # Check for Content Change
                    if row.content_hash != current_hash:
                        logger.info(
                            f"Page {page_id} (idx {i}) changed. Resetting content."
                        )
                        row.content_hash = current_hash
                        row.text_content = None  # Clear OCR
                        row.embedding = None  # Clear Embedding

                        # Invalidate downstream tasks
                        # Note: Tasks are keyed by page_index usually?
                        # We should probably migrate tasks to use page_id too,
                        # but for now let's invalidate based on the NEW index
                        # or just all tasks for this file/page logic.
                        # Ideally, SystemTaskDO key should be page_id.
                        # For now, let's assume keys are "page_{page_index}".
                        # If page moved, the old task key "page_{old_idx}" is irrelevant,
                        # and we need to trigger "page_{new_idx}".
                        # Refactoring SystemTaskDO is out of scope?
                        # Let's clean up tasks for this "logical" page.
                        # Actually, keeping it simple: invalidate tasks for the CURRENT index.
                        # Update: Use page_id for task keys now.
                        page_task_key = f"page_{page_id}"
                        await session.execute(
                            delete(SystemTaskDO)
                            .where(SystemTaskDO.file_id == file_id)
                            .where(SystemTaskDO.key == page_task_key)
                        )
                else:
                    # INSERT path
                    logger.info(f"New page {page_id} at index {i} detected.")
                    new_content = NotePageContentDO(
                        file_id=file_id,
                        page_index=i,
                        page_id=page_id,
                        content_hash=current_hash,
                        text_content=None,
                        embedding=None,
                    )
                    session.add(new_content)

            # 2. Handle Deletions
            # Any page_id in existing_map but NOT in current_page_ids is deleted
            for pid, row in existing_map.items():
                if pid not in current_page_ids:
                    logger.info(f"Page {pid} deleted (was at {row.page_index}).")
                    await session.delete(row)

                    # Cleanup Blobs
                    png_path = get_page_png_path(file_id, pid)
                    try:
                        await self.file_service.blob_storage.delete(
                            CACHE_BUCKET, png_path
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete orphan PNG {pid}: {e}")

                    # Cleanup Tasks
                    await session.execute(
                        delete(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.key == f"page_{pid}")
                    )

            await session.commit()
