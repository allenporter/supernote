"""Tests for `supernote.server.ai.prompts`."""

from __future__ import annotations

from pathlib import Path

from supernote.server.ai.prompts import (
    PageMetadata,
    format_ocr_prompt,
    format_summary_prompt,
    get_summary_json_schema,
)
from supernote.server.utils.note_content import (
    format_page_style,
    normalize_page_style_type,
)
from supernote.server.utils.prompt_loader import PromptLoader


def test_format_ocr_prompt_with_inferred_date(tmp_path: Path) -> None:
    journal_dir = tmp_path / "ocr" / "journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "prompt.md").write_text("Transcribe this page.", encoding="utf-8")

    page_metadata = PageMetadata(
        file_name="Journal.note",
        page_index=0,
        page_id="P20231027123456",
        notebook_create_time=None,
    )
    loader = PromptLoader(tmp_path)

    prompt = format_ocr_prompt(page_metadata, prompt_loader=loader)

    assert "--- Page 1 ---" in prompt
    assert "Notebook Filename: Journal.note" in prompt
    assert "Page ID: P20231027123456" in prompt
    assert "Page Date (Inferred): 2023-10-27" in prompt
    assert "Transcribe this page." in prompt


def test_format_summary_prompt_and_schema(tmp_path: Path) -> None:
    daily_dir = tmp_path / "summary" / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "prompt.md").write_text(
        "Summarize the bullet journal.", encoding="utf-8"
    )
    loader = PromptLoader(tmp_path)

    prompt = format_summary_prompt(
        "Page 1 content", custom_type="daily", prompt_loader=loader
    )

    assert "Summarize the bullet journal." in prompt
    assert "TRANSCRIPT:\nPage 1 content" in prompt

    schema = get_summary_json_schema()
    assert schema["type"] == "object"
    assert "segments" in schema["properties"]


def test_format_page_style_and_style_prompt_fallback(tmp_path: Path) -> None:
    assert format_page_style("style_5mm_dots") == "5mm Dots"
    assert format_page_style("style_four_quadrant_method") == "Four Quadrant Method"
    assert format_page_style("style_h_8mm_ruled_line_a5x2") == "8mm Ruled Line"
    assert format_page_style("style_white_a5x2") == "Blank Canvas"
    assert format_page_style("user_Cornell_Notes") == "Custom: Cornell Notes"
    assert normalize_page_style_type("user_Daily") == "daily"

    quadrant_dir = tmp_path / "ocr" / "four_quadrant_method"
    quadrant_dir.mkdir(parents=True)
    (quadrant_dir / "prompt.md").write_text(
        "Preserve all four quadrants.", encoding="utf-8"
    )
    default_dir = tmp_path / "ocr" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "prompt.md").write_text("Default OCR prompt.", encoding="utf-8")

    loader = PromptLoader(tmp_path)
    page_metadata = PageMetadata(
        file_name="20260618_Meeting.note",
        page_index=0,
        page_id="P20260618120000abc",
        notebook_create_time=None,
        page_style="style_four_quadrant_method",
    )
    prompt = format_ocr_prompt(page_metadata, prompt_loader=loader)
    assert "Page Style: Four Quadrant Method" in prompt
    assert "Preserve all four quadrants." in prompt
