import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import select, text

from supernote.models.base import ProcessingStatus
from supernote.server.constants import (
    DB_WRITE_MAX_RETRIES,
    DB_WRITE_RETRY_BACKOFF_SECONDS,
)
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import DatabaseError
from supernote.server.utils.unique_id import next_id

logger = logging.getLogger(__name__)


async def get_task(
    session_manager: DatabaseSessionManager,
    file_id: int,
    task_type: str,
    key: str,
) -> Optional[SystemTaskDO]:
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
    error: Optional[str] = None,
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
                    INSERT INTO f_system_task (id, file_id, task_type, key, status, last_error, retry_count, create_time, update_time)
                    VALUES (:id, :file_id, :task_type, :key, :status, :error, 0, :now, :now)
                    ON CONFLICT(file_id, task_type, key) DO UPDATE SET
                        status = excluded.status,
                        last_error = excluded.last_error,
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
