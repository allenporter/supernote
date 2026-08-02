from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO


async def test_note_page_content_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for NotePageContentDO."""
    content = NotePageContentDO(
        file_id=1,
        page_index=0,
        page_id="page_123",
        text_content="Sample OCR text",
    )
    db_session.add(content)
    await db_session.commit()

    stmt = select(NotePageContentDO).where(NotePageContentDO.id == content.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.file_id == 1
    assert fetched.page_index == 0
    assert fetched.page_id == "page_123"
    assert fetched.text_content == "Sample OCR text"


async def test_system_task_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for SystemTaskDO."""
    task = SystemTaskDO(
        file_id=1,
        task_type="OCR",
        key="page_0",
        status=ProcessingStatus.PENDING,
    )
    db_session.add(task)
    await db_session.commit()

    stmt = select(SystemTaskDO).where(SystemTaskDO.id == task.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.file_id == 1
    assert fetched.task_type == "OCR"
    assert fetched.status == ProcessingStatus.PENDING
