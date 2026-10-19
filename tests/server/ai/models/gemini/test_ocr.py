"""Tests for `supernote.server.ai.models.gemini.ocr`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types

from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.ocr import GeminiOcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt


async def test_gemini_ocr_model() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        backend = GeminiBackend(api_key="fake-key")
        mock_client = mock_client_cls.return_value
        backend._client = mock_client

        ocr_model = GeminiOcrModel(backend, "gemini-2.0-flash-exp")
        mock_ocr_resp = MagicMock()
        mock_ocr_resp.text = "Handwritten text content"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_ocr_resp)

        page_meta = PageMetadata(
            file_name="real.note",
            page_index=0,
            page_id="p0",
            notebook_create_time=None,
        )
        ocr_prompt = format_ocr_prompt(page_meta)
        ocr_result = await ocr_model.extract_text(b"fake-png-data", ocr_prompt)
        assert ocr_result == "Handwritten text content"

        _, kwargs = mock_client.aio.models.generate_content.call_args
        assert kwargs["model"] == "gemini-2.0-flash-exp"
        content_obj = kwargs["contents"][0]
        assert len(content_obj.parts) == 2
        assert content_obj.parts[0].text == ocr_prompt
        assert "Notebook Filename: real.note" in content_obj.parts[0].text
        assert content_obj.parts[1].inline_data.data == b"fake-png-data"
        assert kwargs["config"] == types.GenerateContentConfig(
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH
        )
