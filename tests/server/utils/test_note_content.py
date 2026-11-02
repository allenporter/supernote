"""Tests for `supernote.server.utils.note_content`."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.notebook import load_notebook
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.utils.note_content import (
    extract_page_keyword_texts,
    format_page_metadata,
    format_page_style,
    get_page_content_by_id,
    get_page_metadata_for_page,
    infer_page_date,
    keyword_to_vo,
    link_to_vo,
    normalize_page_style_type,
    parse_keywords_json,
    parse_links_json,
    parse_titles_json,
    rect_to_vo,
    title_to_vo,
)


async def test_get_page_content_and_metadata_helpers(db_session: AsyncSession) -> None:
    row = NotePageContentDO(
        file_id=50,
        page_index=0,
        page_id="P20260101000000abc",
        text_content="hello",
    )
    meta_row = NotePageMetadataDO(
        user_id=1,
        file_id=50,
        page_index=0,
        page_id="P20260101000000abc",
        page_style="style_5mm_dots",
        has_ink=True,
        has_drawables=True,
        has_content=True,
    )
    legacy_meta_row = NotePageMetadataDO(
        user_id=1,
        file_id=51,
        page_index=1,
        page_id="",
        page_style="style_white",
        has_ink=False,
        has_drawables=False,
        has_content=False,
    )
    db_session.add_all([row, meta_row, legacy_meta_row])
    await db_session.commit()

    found = await get_page_content_by_id(db_session, 50, "P20260101000000abc")
    assert found is not None
    assert found.text_content == "hello"
    assert await get_page_content_by_id(db_session, 50, "P_MISSING") is None

    by_id = await get_page_metadata_for_page(
        db_session, 50, page_id="P20260101000000abc"
    )
    assert by_id is not None
    assert by_id.page_style == "style_5mm_dots"

    by_idx = await get_page_metadata_for_page(db_session, 51, page_id="", page_index=1)
    assert by_idx is not None
    assert by_idx.has_ink is False

    assert await get_page_metadata_for_page(db_session, 51) is None


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


def test_vo_converters_and_json_parsers() -> None:
    assert rect_to_vo(None) is None
    assert parse_keywords_json(None) == []
    assert parse_keywords_json("bad") == []
    assert parse_keywords_json("{}") == []
    assert parse_titles_json(None) == []
    assert parse_titles_json("bad") == []
    assert parse_titles_json("{}") == []
    assert parse_links_json(None) == []
    assert parse_links_json("bad") == []
    assert parse_links_json("{}") == []

    test_note = load_notebook(Path("tests/testdata/philips/test.note"), policy="loose")
    kw_json = json.dumps([keyword_to_vo(kw).to_dict() for kw in test_note.keywords])
    ti_json = json.dumps([title_to_vo(t).to_dict() for t in test_note.titles])
    assert len(parse_keywords_json(kw_json)) == 2
    assert len(extract_page_keyword_texts(kw_json)) == 2
    assert len(parse_titles_json(ti_json)) == 2

    links_note = load_notebook(
        Path("tests/testdata/nelinory/A5X_TestNote_Links.note"), policy="loose"
    )
    lk_json = json.dumps([link_to_vo(lk).to_dict() for lk in links_note.links])
    assert len(parse_links_json(lk_json)) == 8
