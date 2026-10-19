"""Tests for `supernote.server.ai.models.gemini.summary`."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.summary import GeminiSummaryModel
from supernote.server.ai.prompts import format_summary_prompt


async def test_gemini_summary_model() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        backend = GeminiBackend(api_key="fake-key")
        mock_client = mock_client_cls.return_value
        backend._client = mock_client

        summary_model = GeminiSummaryModel(backend, "gemini-2.0-flash-exp")
        mock_sum_resp = MagicMock()
        mock_sum_resp.text = json.dumps(
            {
                "segments": [
                    {
                        "date_range": "2023-10-27",
                        "summary": "AI Summary Output",
                        "extracted_dates": ["2023-10-27"],
                        "page_refs": [1, 2],
                    }
                ]
            }
        )
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_sum_resp)

        summary_prompt = format_summary_prompt("Page 1 text", custom_type="real")
        sum_result = await summary_model.summarize(summary_prompt)
        assert summary_model.model_id == "gemini-2.0-flash-exp"
        assert len(sum_result.segments) == 1
        assert sum_result.segments[0].summary == "AI Summary Output"
        assert sum_result.segments[0].page_refs == [1, 2]

        mock_empty_resp = MagicMock()
        mock_empty_resp.text = ""
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_empty_resp
        )
        empty_result = await summary_model.summarize("Page 1 text")
        assert empty_result.segments == []

        mock_bad_resp = MagicMock()
        mock_bad_resp.text = "not valid json"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_bad_resp)
        with pytest.raises(AIError, match="Failed to parse Gemini summary JSON"):
            await summary_model.summarize("Page 1 text")
