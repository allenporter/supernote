"""Tests for `supernote.server.ai.prompts`."""

from __future__ import annotations

from unittest.mock import MagicMock

from supernote.server.ai.prompts import (
    PageMetadata,
    format_ocr_prompt,
    format_summary_prompt,
    get_summary_json_schema,
)
from supernote.server.utils.prompt_loader import PromptId


def test_format_ocr_prompt_with_inferred_date() -> None:
    page_metadata = PageMetadata(
        file_name="Journal.note",
        page_index=0,
        page_id="P20231027123456",
        notebook_create_time=None,
    )
    mock_loader = MagicMock()
    mock_loader.get_prompt.return_value = "Transcribe this page."

    prompt = format_ocr_prompt(page_metadata, prompt_loader=mock_loader)

    mock_loader.get_prompt.assert_called_once_with(
        PromptId.OCR_TRANSCRIPTION, custom_type="journal"
    )
    assert "--- Page 1 ---" in prompt
    assert "Notebook Filename: Journal.note" in prompt
    assert "Page ID: P20231027123456" in prompt
    assert "Page Date (Inferred): 2023-10-27" in prompt
    assert "Transcribe this page." in prompt


def test_format_summary_prompt_and_schema() -> None:
    mock_loader = MagicMock()
    mock_loader.get_prompt.return_value = "Summarize the bullet journal."

    prompt = format_summary_prompt(
        "Page 1 content", custom_type="daily", prompt_loader=mock_loader
    )

    mock_loader.get_prompt.assert_called_once_with(
        PromptId.SUMMARY_GENERATION, custom_type="daily"
    )
    assert "Summarize the bullet journal." in prompt
    assert "TRANSCRIPT:\nPage 1 content" in prompt

    schema = get_summary_json_schema()
    assert schema["type"] == "object"
    assert "segments" in schema["properties"]
