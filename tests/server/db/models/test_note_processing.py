from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    SystemTaskDO,
)


async def test_note_metadata_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for NoteMetadataDO."""
    meta = NoteMetadataDO(
        user_id=10,
        file_id=42,
        native_file_id="F202611020001",
        file_type="note",
        equipment="N5",
        signature="SN_FILE_VER_20230015",
        width=1920,
        height=2560,
        total_pages=2,
        recogn_language="en_US",
        is_realtime_recognition=True,
        metadata_json='{"type":"note"}',
    )
    db_session.add(meta)
    await db_session.commit()

    fetched = await db_session.get(NoteMetadataDO, (10, 42))
    assert fetched is not None
    assert fetched.native_file_id == "F202611020001"
    assert fetched.equipment == "N5"
    assert fetched.width == 1920
    assert fetched.height == 2560
    assert fetched.total_pages == 2
    assert fetched.is_realtime_recognition is True
    assert fetched.metadata_json == '{"type":"note"}'


async def test_note_page_content_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for NotePageContentDO."""
    content = NotePageContentDO(
        file_id=1,
        page_index=0,
        page_id="page_123",
        page_style="style_5mm_dots",
        has_ink=True,
        has_drawables=True,
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
    assert fetched.page_style == "style_5mm_dots"
    assert fetched.has_ink is True
    assert fetched.has_drawables is True
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
