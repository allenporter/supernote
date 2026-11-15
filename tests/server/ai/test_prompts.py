"""Tests for `supernote.server.ai.prompts`."""

from __future__ import annotations

from pathlib import Path

from supernote.server.ai.prompts import (
    PageMetadata,
    format_ocr_prompt,
    format_summary_prompt,
    get_summary_json_schema,
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


def test_format_ocr_prompt_routes_by_page_style_when_filename_has_no_custom_prompt(
    tmp_path: Path,
) -> None:
    """Verify page_style_basis selects a custom OCR prompt when file_name_basis has none."""
    daily_dir = tmp_path / "ocr" / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "prompt.md").write_text(
        "Daily template instructions.", encoding="utf-8"
    )
    loader = PromptLoader(tmp_path)

    page_metadata = PageMetadata(
        file_name="2026_BuJo.note",
        page_index=0,
        page_id="P20260301090000",
        notebook_create_time=None,
        page_style="user_Daily_a5x2",
        keywords=["Project Alpha", "Dr. Patel"],
    )

    prompt = format_ocr_prompt(page_metadata, prompt_loader=loader)

    assert "Daily template instructions." in prompt
    assert "Page Keywords: Project Alpha, Dr. Patel" in prompt


def test_format_ocr_prompt_prefers_filename_prompt_over_page_style(
    tmp_path: Path,
) -> None:
    """Verify file_name_basis takes precedence over page_style_basis when both have custom prompts."""
    for name, text in (
        ("daily", "Daily prompt from filename."),
        ("weekly", "Weekly prompt from page_style."),
    ):
        d = tmp_path / "ocr" / name
        d.mkdir(parents=True)
        (d / "prompt.md").write_text(text, encoding="utf-8")
    loader = PromptLoader(tmp_path)

    page_metadata = PageMetadata(
        file_name="Daily.note",
        page_index=0,
        page_id="P20260301090000",
        notebook_create_time=None,
        page_style="user_Weekly",
    )

    prompt = format_ocr_prompt(page_metadata, prompt_loader=loader)

    assert "Daily prompt from filename." in prompt
    assert "Weekly prompt from page_style." not in prompt
