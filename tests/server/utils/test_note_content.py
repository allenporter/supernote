from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_metadata_for_page,
    infer_page_date,
)


async def test_get_page_metadata_for_page_prefers_page_id_then_page_index(
    db_session: AsyncSession,
) -> None:
    """Verify get_page_metadata_for_page resolves by page_id first and falls back to page_index."""
    db_session.add_all(
        [
            NotePageMetadataDO(
                user_id=7,
                file_id=500,
                page_index=0,
                page_id="P20260101000000a",
                has_ink=True,
                has_drawables=True,
            ),
            NotePageMetadataDO(
                user_id=7,
                file_id=500,
                page_index=1,
                page_id="P20260102000000b",
                has_ink=False,
                has_drawables=False,
            ),
        ]
    )
    await db_session.commit()

    by_id = await get_page_metadata_for_page(
        db_session, 500, page_id="P20260102000000b", page_index=0
    )
    assert by_id is not None
    assert by_id.page_index == 1
    assert by_id.has_drawables is False

    by_index = await get_page_metadata_for_page(
        db_session, 500, page_id="unknown_id", page_index=0
    )
    assert by_index is not None
    assert by_index.page_id == "P20260101000000a"

    assert await get_page_metadata_for_page(db_session, 999, page_id="p0") is None


def test_infer_page_date_and_format_page_metadata() -> None:
    """Verify infer_page_date extracts YYYYMMDD and format_page_metadata renders the header."""
    dt = infer_page_date("P20261109123456xyz")
    assert dt is not None
    assert dt.strftime("%Y-%m-%d") == "2026-11-09"
    assert infer_page_date("invalid") is None

    block = format_page_metadata(
        page_index=0,
        page_id="P20261109123456xyz",
        file_name="Journal.note",
        include_section_divider=True,
    )
    assert "--- Page 1 ---" in block
    assert "Notebook Filename: Journal.note" in block
    assert "Page Date (Inferred): 2026-11-09" in block
    assert block.endswith("---")
