"""Database checkpoint helpers (`get_task`, `update_task_status`) for `SystemTaskDO`.

Used by `supernote.server.services.processor_modules.ProcessorModule` to read and atomically
upsert per-file and per-page pipeline task states (`ProcessingStatus`) with SQLite write-retry
backoff (`DB_WRITE_MAX_RETRIES`). See `supernote.guides.note_processing_design`.
"""

import asyncio
import logging
import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.constants import (
    DB_WRITE_MAX_RETRIES,
    DB_WRITE_RETRY_BACKOFF_SECONDS,
)
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import DatabaseError
from supernote.server.utils.unique_id import next_id

logger = logging.getLogger(__name__)


async def get_task(
    session_manager: DatabaseSessionManager,
    file_id: int,
    task_type: str,
    key: str,
) -> SystemTaskDO | None:
    """Retrieve a SystemTaskDO by file_id, task_type, and key."""
    async with session_manager.session() as session:
        return (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == task_type)
                    .where(SystemTaskDO.key == key)
                )
            )
            .scalars()
            .first()
        )


async def update_task_status(
    session_manager: DatabaseSessionManager,
    file_id: int,
    task_type: str,
    key: str,
    status: ProcessingStatus,
    error: str | None = None,
    data: str | None = None,
) -> None:
    """Create or update a SystemTaskDO status atomically with retries for lock conflicts."""
    max_retries = DB_WRITE_MAX_RETRIES
    backoff = DB_WRITE_RETRY_BACKOFF_SECONDS

    for attempt in range(max_retries):
        try:
            async with session_manager.session() as session:
                now = int(time.time() * 1000)
                # Using native SQL UPSERT because SQLite's ON CONFLICT
                # is very robust for our needs and avoids SELECT-then-UPDATE races.
                # We must provide 'id' and 'retry_count' manually for the INSERT part.
                sql = text(
                    """
                    INSERT INTO f_system_task (id, file_id, task_type, key, status, data, last_error, retry_count, create_time, update_time)
                    VALUES (:id, :file_id, :task_type, :key, :status, :data, :error, 0, :now, :now)
                    ON CONFLICT(file_id, task_type, key) DO UPDATE SET
                        status = excluded.status,
                        data = excluded.data,
                        last_error = excluded.last_error,
                        retry_count = CASE
                            WHEN excluded.status = 'FAILED' AND f_system_task.status = 'FAILED'
                            THEN f_system_task.retry_count + 1
                            ELSE 0
                        END,
                        update_time = excluded.update_time
                """
                )

                await session.execute(
                    sql,
                    {
                        "id": next_id(),
                        "file_id": file_id,
                        "task_type": task_type,
                        "key": key,
                        "status": status,
                        "data": data,
                        "error": error,
                        "now": now,
                    },
                )
                await session.commit()
                return  # Success!
        except DatabaseError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                logger.warning(
                    f"Database locked during task status update for file {file_id} (attempt {attempt + 1}/{max_retries}). Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                raise


async def has_incomplete_page_ocr(
    session: AsyncSession,
    file_id: int,
    page_id: str | None = None,
) -> bool:
    """Return True if target page(s) have failed/pending OCR prerequisites or un-checkpointed stale text.

    Because `PageHashingModule` preserves `NotePageContentDO.text_content` across
    `content_hash` invalidation (while deleting per-page `SystemTaskDO` rows),
    downstream consumers (`EmbeddingModule` and `SummaryModule`) use this check so
    skipped, disabled, or failed OCR stages never consume stale pre-edit transcripts.
    """
    key_filter = (
        SystemTaskDO.key == f"page_{page_id}"
        if page_id is not None
        else SystemTaskDO.key.like("page_%")
    )
    non_completed_prereq = (
        await session.execute(
            select(SystemTaskDO.id)
            .where(
                SystemTaskDO.file_id == file_id,
                key_filter,
                SystemTaskDO.status != ProcessingStatus.COMPLETED,
                SystemTaskDO.task_type.in_(
                    (TaskType.PNG_CONVERSION.value, TaskType.OCR_EXTRACTION.value)
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if non_completed_prereq is not None:
        return True

    hashing_exists = (
        await session.execute(
            select(SystemTaskDO.id)
            .where(
                SystemTaskDO.file_id == file_id,
                SystemTaskDO.task_type == TaskType.PAGE_HASHING.value,
                SystemTaskDO.key == "global",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if hashing_exists is None:
        note_meta_exists = (
            await session.execute(
                select(NoteMetadataDO.file_id)
                .where(NoteMetadataDO.file_id == file_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if note_meta_exists is None:
            return False

    completed_ocr = (
        select(SystemTaskDO.id)
        .where(
            SystemTaskDO.file_id == NotePageContentDO.file_id,
            SystemTaskDO.task_type == TaskType.OCR_EXTRACTION.value,
            SystemTaskDO.key == "page_" + NotePageContentDO.page_id,
            SystemTaskDO.status == ProcessingStatus.COMPLETED,
        )
        .correlate(NotePageContentDO)
    )
    missing_ocr_stmt = (
        select(NotePageContentDO.id)
        .where(
            NotePageContentDO.file_id == file_id,
            NotePageContentDO.page_id != "",
            ~completed_ocr.exists(),
        )
        .limit(1)
    )
    if page_id is not None:
        missing_ocr_stmt = missing_ocr_stmt.where(NotePageContentDO.page_id == page_id)
    return (await session.execute(missing_ocr_stmt)).scalar_one_or_none() is not None
