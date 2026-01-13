import asyncio
import logging
import time
from functools import partial
from typing import Any, Optional

from sqlalchemy import delete, select

from supernote.notebook.parser import parse_metadata
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.hashing import get_md5_hash

logger = logging.getLogger(__name__)


def _parse_helper(path: str) -> Any:
    with open(path, "rb") as f:
        return parse_metadata(f)  # type: ignore[arg-type]


class PageHashingModule(ProcessorModule):
    """Module responsible for detecting changes in .note files at the page level.

    This module performs the following:
    1.  Parses the binary .note file using `SupernoteParser`.
    2.  Computes a unique MD5 hash for each page based on its layer metadata.
    3.  Updates the `NotePageContentDO` table:
        -   Creates entries for new pages.
        -   Updates hashes for changed pages and invalidates downstream data (OCR, Embeddings) to trigger reprocessing.
        -   Removes entries for deleted pages.
    4.  Updates the `SystemTaskDO` status for the 'HASHING' task.

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
    ) -> bool:
        """Check if hashing is needed for the file.

        Hashing acts as the change detector, so it MUST run every time the file is processed.
        It is cheap to run because parsing the .note structure is fast compared to OCR/Embeddings.
        """
        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        """Parses the .note file, computes page hashes, and updates NotePageContentDO."""
        logger.info(f"Starting PageHashingModule for file_id={file_id}")

        # 1. Resolve file path
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

        # 2. Parse .note file
        try:
            # Run parser in thread pool
            loop = asyncio.get_running_loop()
            metadata = await loop.run_in_executor(
                None, partial(_parse_helper, str(abs_path))
            )

        except Exception as e:
            logger.error(f"Failed to parse .note file {file_id}: {e}")
            return

        # 3. Iterate pages and update DB
        total_pages = metadata.get_total_pages()
        if not metadata.pages:
            # Should not happen if total_pages > 0, but safe check for types
            return

        async with session_manager.session() as session:
            for i in range(total_pages):
                # Calculate Hash
                # Constructing a unique signature for the page content:
                page_info = metadata.pages[i]
                # Canonical string representation of page metadata for hashing
                page_hash_input = str(page_info)

                # Check for existing content
                existing_content = (
                    (
                        await session.execute(
                            select(NotePageContentDO)
                            .where(NotePageContentDO.file_id == file_id)
                            .where(NotePageContentDO.page_index == i)
                        )
                    )
                    .scalars()
                    .first()
                )

                current_hash = get_md5_hash(page_hash_input)

                if existing_content:
                    if existing_content.content_hash != current_hash:
                        logger.info(
                            f"Page {i} of file {file_id} changed. Resetting content."
                        )
                        existing_content.content_hash = current_hash
                        existing_content.text_content = None  # Clear OCR
                        existing_content.embedding = None  # Clear Embedding
                        # We do NOT delete the row, just clear validity.

                        # Invalidate downstream tasks to force re-processing
                        page_task_key = f"page_{i}"
                        await session.execute(
                            delete(SystemTaskDO)
                            .where(SystemTaskDO.file_id == file_id)
                            .where(
                                SystemTaskDO.task_type.in_(
                                    [
                                        "PNG_CONVERSION",
                                        "OCR_EXTRACTION",
                                        "EMBEDDING_GENERATION",
                                    ]
                                )
                            )
                            .where(SystemTaskDO.key == page_task_key)
                        )
                else:
                    logger.info(f"New page {i} for file {file_id} detected.")
                    new_content = NotePageContentDO(
                        file_id=file_id,
                        page_index=i,
                        content_hash=current_hash,
                        text_content=None,
                        embedding=None,
                    )
                    session.add(new_content)

            # 4. Handle Page Deletions
            # If the notebook shrank (pages removed), delete orphaned entries.

            await session.execute(
                delete(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .where(NotePageContentDO.page_index >= total_pages)
            )

            # 5. Mark Hashing Task as Complete
            task_key = "global"
            existing_task = (
                (
                    await session.execute(
                        select(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.task_type == self.task_type)
                        .where(SystemTaskDO.key == task_key)
                    )
                )
                .scalars()
                .first()
            )

            if not existing_task:
                existing_task = SystemTaskDO(
                    file_id=file_id,
                    task_type=self.task_type,
                    key=task_key,
                    status="COMPLETED",
                )
                session.add(existing_task)
            else:
                existing_task.status = "COMPLETED"
                existing_task.last_error = None
                existing_task.update_time = int(time.time() * 1000)

            await session.commit()
