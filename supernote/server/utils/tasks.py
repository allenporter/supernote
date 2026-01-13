import time
from typing import Optional

from sqlalchemy import select

from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager


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
    status: str,
    error: Optional[str] = None,
) -> None:
    """Create or update a SystemTaskDO status."""
    async with session_manager.session() as session:
        existing_task = (
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

        if not existing_task:
            existing_task = SystemTaskDO(
                file_id=file_id,
                task_type=task_type,
                key=key,
                status=status,
                last_error=error,
            )
            session.add(existing_task)
        else:
            existing_task.status = status
            existing_task.last_error = error
            existing_task.update_time = int(time.time() * 1000)

        await session.commit()
