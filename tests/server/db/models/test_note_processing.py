from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)


async def test_note_metadata_crud(db_session: AsyncSession) -> None:
    """Test CRUD and default values for NoteMetadataDO."""
    meta = NoteMetadataDO(
        user_id=7,
        file_id=42,
        native_file_id="F20260101",
        file_type="note",
        signature="SN_FILE_VER_20230015",
        total_pages=1,
    )
    db_session.add(meta)
    await db_session.commit()

    fetched = await db_session.get(NoteMetadataDO, (7, 42))
    assert fetched is not None
    assert fetched.native_file_id == "F20260101"
    assert fetched.file_type == "note"
    assert fetched.signature == "SN_FILE_VER_20230015"
    assert fetched.total_pages == 1
    assert fetched.header_json == "{}"
    assert fetched.footer_json == "{}"


async def test_note_page_metadata_crud(db_session: AsyncSession) -> None:
    """Test CRUD and default values for NotePageMetadataDO."""
    page_meta = NotePageMetadataDO(
        user_id=7,
        file_id=42,
        page_index=0,
        page_id="P20260101",
        page_style="style_5mm_dots",
        has_ink=True,
        has_drawables=True,
    )
    db_session.add(page_meta)
    await db_session.commit()

    fetched = await db_session.get(NotePageMetadataDO, (7, 42, 0))
    assert fetched is not None
    assert fetched.page_id == "P20260101"
    assert fetched.content_hash == ""
    assert fetched.page_style == "style_5mm_dots"
    assert fetched.has_ink is True
    assert fetched.has_drawables is True
    assert fetched.page_json == "{}"
    assert fetched.keywords_json == "[]"
    assert fetched.titles_json == "[]"
    assert fetched.links_json == "[]"


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
