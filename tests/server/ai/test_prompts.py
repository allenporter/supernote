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


def test_format_ocr_prompt_with_vocabulary(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr" / "common"
    ocr_dir.mkdir(parents=True)
    (ocr_dir / "prompt.md").write_text("Transcribe this page.", encoding="utf-8")
    page_metadata = PageMetadata(
        file_name="Plan.note",
        page_index=0,
        page_id="P1",
        notebook_create_time=None,
    )
    loader = PromptLoader(tmp_path)

    plain = format_ocr_prompt(page_metadata, prompt_loader=loader)
    assert "may appear in the text" not in plain

    prompt = format_ocr_prompt(
        page_metadata, vocabulary=["Lovelace", "ks-tilt"], prompt_loader=loader
    )
    assert prompt.startswith(plain)
    assert prompt.endswith(
        "These names and terms may appear in the text: Lovelace, ks-tilt. "
        "If a handwritten word closely matches one of them, prefer that spelling. "
        "Never insert one of these terms where the handwriting does not support it."
    )


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
