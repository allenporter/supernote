from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ProcessingStatus
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)


async def test_note_metadata_and_page_metadata_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for NoteMetadataDO and NotePageMetadataDO."""
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
        header_json='{"FILE_TYPE":"NOTE"}',
        footer_json='{"FILE_FEATURE":"24"}',
    )
    page_meta = NotePageMetadataDO(
        user_id=10,
        file_id=42,
        page_index=0,
        page_id="P20261102120000abc",
        page_style="style_5mm_dots",
        orientation="1000",
        recogn_status=1,
        has_ink=True,
        has_drawables=True,
        has_textbox=False,
        has_vector_graph=False,
        has_content=True,
        page_json='{"PAGEID":"P20261102120000abc"}',
        keywords_json='[{"pageNumber":0,"text":"stroller","rect":null}]',
    )
    db_session.add_all([meta, page_meta])
    await db_session.commit()

    fetched = await db_session.get(NoteMetadataDO, (10, 42))
    assert fetched is not None
    assert fetched.native_file_id == "F202611020001"
    assert fetched.equipment == "N5"
    assert fetched.width == 1920
    assert fetched.height == 2560
    assert fetched.total_pages == 2
    assert fetched.is_realtime_recognition is True
    assert fetched.header_json == '{"FILE_TYPE":"NOTE"}'

    fetched_page = await db_session.get(NotePageMetadataDO, (10, 42, 0))
    assert fetched_page is not None
    assert fetched_page.page_id == "P20261102120000abc"
    assert fetched_page.page_style == "style_5mm_dots"
    assert fetched_page.has_ink is True
    assert fetched_page.has_drawables is True
    assert fetched_page.has_content is True


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
