from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_metadata_for_page,
    infer_page_date,
)


async def test_get_page_metadata_for_page_scopes_user_and_avoids_unsafe_slot_fallback(
    db_session: AsyncSession,
) -> None:
    """Verify get_page_metadata_for_page scopes by user_id, never falls back to page_index on page_id miss, and uses page_index only when page_id is empty."""
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
                page_id="",
                has_ink=False,
                has_drawables=False,
            ),
        ]
    )
    await db_session.commit()

    by_id = await get_page_metadata_for_page(
        db_session, 7, 500, page_id="P20260101000000a", page_index=1
    )
    assert by_id is not None
    assert by_id.page_index == 0
    assert by_id.has_drawables is True

    # Wrong user_id must not leak metadata
    assert (
        await get_page_metadata_for_page(
            db_session, 99, 500, page_id="P20260101000000a", page_index=0
        )
        is None
    )

    # Non-empty unknown page_id must NOT fall back to page_index=0
    assert (
        await get_page_metadata_for_page(
            db_session, 7, 500, page_id="unknown_id", page_index=0
        )
        is None
    )

    # Legacy page without page_id resolves cleanly by PK (user_id, file_id, page_index)
    legacy = await get_page_metadata_for_page(
        db_session, 7, 500, page_id="", page_index=1
    )
    assert legacy is not None
    assert legacy.page_index == 1
    assert legacy.has_drawables is False


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
