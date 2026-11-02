"""Tests for `supernote.server.utils.note_content`."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.notebook import load_notebook
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.utils.note_content import (
    extract_keywords_by_page_index,
    format_page_metadata,
    format_page_style,
    get_page_content_by_id,
    infer_page_date,
    normalize_page_style_type,
)


async def test_get_page_content_by_id(db_session: AsyncSession) -> None:
    row = NotePageContentDO(
        file_id=50,
        page_index=0,
        page_id="P20260101000000abc",
        text_content="hello",
    )
    db_session.add(row)
    await db_session.commit()

    found = await get_page_content_by_id(db_session, 50, "P20260101000000abc")
    assert found is not None
    assert found.text_content == "hello"

    missing = await get_page_content_by_id(db_session, 50, "P_MISSING")
    assert missing is None


def test_infer_page_date() -> None:
    assert infer_page_date("P20231027123456abc") == datetime(2023, 10, 27)
    assert infer_page_date("") is None
    assert infer_page_date("X20231027") is None
    assert infer_page_date("Pshort") is None
    assert infer_page_date("P20239999123456") is None


@pytest.mark.parametrize(
    ("raw_style", "expected_slug", "expected_label"),
    [
        (None, None, None),
        ("", None, None),
        ("   ", None, None),
        ("style_white", "white", "Blank Canvas"),
        ("style_white_a5x2", "white", "Blank Canvas"),
        ("style_h_white", "white", "Blank Canvas"),
        ("style_5mm_dots", "5mm_dots", "5mm Dots"),
        (
            "style_h_8mm_ruled_line_a5x2",
            "8mm_ruled_line",
            "8mm Ruled Line",
        ),
        (
            "style_four_quadrant_method",
            "four_quadrant_method",
            "Four Quadrant Method",
        ),
        ("user_team_meeting", "team_meeting", "Custom: Team Meeting"),
        ("user_pdf_Pdf_Template_1", "pdf_pdf_template_1", "Custom: Pdf Pdf Template 1"),
        ("user_DailyPlanner_n6", "dailyplanner", "Custom: DailyPlanner"),
        ("user_", None, "Custom Template"),
        ("style____", None, None),
    ],
)
def test_normalize_and_format_page_style(
    raw_style: str | None,
    expected_slug: str | None,
    expected_label: str | None,
) -> None:
    assert normalize_page_style_type(raw_style) == expected_slug
    assert format_page_style(raw_style) == expected_label


def test_format_page_metadata_includes_style_and_keywords() -> None:
    block = format_page_metadata(
        page_index=1,
        page_id="P20260618090000xyz",
        file_name="Journal.note",
        notebook_create_time=1700000000000,
        page_style="style_four_quadrant_method",
        keywords=["stroller", "  ", "travel"],
        include_section_divider=True,
    )
    assert "--- Page 2 ---" in block
    assert "Notebook Filename: Journal.note" in block
    assert "Notebook Created:" in block
    assert "Page ID: P20260618090000xyz" in block
    assert "Page Date (Inferred): 2026-06-18" in block
    assert "Page Style: Four Quadrant Method" in block
    assert "Page Keywords: stroller, travel" in block
    assert block.endswith("\n---")


def test_extract_keywords_by_page_index() -> None:
    assert extract_keywords_by_page_index(None) == {}
    assert extract_keywords_by_page_index("") == {}
    assert extract_keywords_by_page_index("not valid json") == {}

    stroller_path = Path("tests/testdata/mmujynya/stroller.note")
    nb = load_notebook(stroller_path, policy="loose")
    by_page = extract_keywords_by_page_index(nb.metadata.to_json())
    assert 0 in by_page
    assert len(by_page[0]) >= 1
