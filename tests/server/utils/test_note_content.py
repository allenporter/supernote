"""Unit tests for `supernote.server.utils.note_content`."""

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.utils.note_content import (
    format_page_metadata,
    get_page_content_by_id,
    get_page_keywords_map,
    infer_page_date,
    normalize_page_style_type,
)


async def test_get_page_content_by_id_undefers_previous_text(
    db_session: AsyncSession,
) -> None:
    """Verify get_page_content_by_id eagerly loads deferred previous_text."""
    db_session.add(
        NotePageContentDO(
            file_id=42,
            page_index=0,
            page_id="P20261123090000abc",
            content_hash="h1",
            text_content="Current text",
            previous_text="Prior text",
        )
    )
    await db_session.commit()
    db_session.expire_all()

    row = await get_page_content_by_id(db_session, 42, "P20261123090000abc")
    assert row is not None
    assert row.text_content == "Current text"
    assert row.previous_text == "Prior text"
    assert await get_page_content_by_id(db_session, 42, "missing") is None


async def test_get_page_keywords_map_scopes_by_user_and_file(
    db_session: AsyncSession,
) -> None:
    """Verify get_page_keywords_map returns non-empty keywords scoped to (user_id, file_id)."""
    db_session.add_all(
        [
            NotePageMetadataDO(
                user_id=7,
                file_id=100,
                page_index=0,
                page_id="p0",
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "Roadmap"}]',
            ),
            NotePageMetadataDO(
                user_id=7,
                file_id=100,
                page_index=1,
                page_id="p1",
                keywords_json="[]",
            ),
            NotePageMetadataDO(
                user_id=8,
                file_id=100,
                page_index=0,
                page_id="p0",
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "OtherUser"}]',
            ),
        ]
    )
    await db_session.commit()

    assert await get_page_keywords_map(db_session, user_id=7, file_id=100) == {
        "p0": ["Roadmap"]
    }


@pytest.mark.parametrize(
    ("raw_style", "expected"),
    [
        (None, None),
        ("   ", None),
        ("user_Daily", "daily"),
        ("style_h_8mm_ruled_line_a5x2", "8mm_ruled_line"),
        ("style_5mm_dots_n6", "5mm_dots"),
    ],
)
def test_normalize_page_style_type(raw_style: str | None, expected: str | None) -> None:
    """Verify Supernote page styles normalize to canonical prompt slugs."""
    assert normalize_page_style_type(raw_style) == expected


@pytest.mark.parametrize(
    ("page_id", "expected"),
    [
        ("P20261123090500abc", datetime(2026, 11, 23)),
        ("P99999999", None),
        ("invalid", None),
        ("", None),
    ],
)
def test_infer_page_date(page_id: str, expected: datetime | None) -> None:
    """Verify date inference from Supernote PAGEID prefixes."""
    assert infer_page_date(page_id) == expected


def test_format_page_metadata_includes_optional_fields() -> None:
    """Verify format_page_metadata renders filename, inferred date, keywords, and divider."""
    rendered = format_page_metadata(
        page_index=1,
        page_id="P20261123090500abc",
        file_name="Daily.note",
        keywords=["  Sprint  ", ""],
        include_section_divider=True,
    )
    assert rendered == (
        "--- Page 2 ---\n"
        "Notebook Filename: Daily.note\n"
        "Page ID: P20261123090500abc\n"
        "Page Date (Inferred): 2026-11-23\n"
        "Page Keywords: Sprint\n"
        "---"
    )
