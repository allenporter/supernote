from unittest.mock import patch

from supernote.server.utils.ocr_prompt import PageMetadata, create_ocr_prompt
from supernote.server.utils.prompt_loader import PromptId


def test_create_ocr_prompt() -> None:
    metadata = PageMetadata(
        file_name="Daily.note",
        page_index=2,
        page_id="P20231027123456",
        notebook_create_time=None,
    )
    with patch("supernote.server.utils.ocr_prompt.PROMPT_LOADER") as mock_loader:
        mock_loader.get_prompt.return_value = "Transcribe this page."
        prompt = create_ocr_prompt(metadata)

    mock_loader.get_prompt.assert_called_once_with(
        PromptId.OCR_TRANSCRIPTION, custom_type="daily"
    )
    assert prompt == (
        "--- Page 3 ---\n"
        "Notebook Filename: Daily.note\n"
        "Page ID: P20231027123456\n"
        "Page Date (Inferred): 2023-10-27\n"
        "---\n"
        "\n"
        "Transcribe this page."
    )
