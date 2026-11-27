"""Tests for `supernote.server.components.gemini.summary`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import (
    SummaryResponse,
    SummarySegment,
    format_summary_prompt,
)
from supernote.server.config import ModelConfig, ProviderConfig

from .conftest import FakeGeminiServer, LoadGeminiModels

SEGMENTS = {
    "segments": [
        {
            "date_range": "2023-10-27",
            "summary": "AI Summary Output",
            "extracted_dates": ["2023-10-27"],
            "page_refs": [1, 2],
        }
    ]
}
EXPECTED = SummaryResponse(
    segments=[
        SummarySegment(
            date_range="2023-10-27",
            summary="AI Summary Output",
            extracted_dates=["2023-10-27"],
            page_refs=[1, 2],
        )
    ]
)


async def test_gemini_summary_model(
    gemini_summary_model: SummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = json.dumps(SEGMENTS)

    summary_prompt = format_summary_prompt("Page 1 text", custom_type="real")
    assert await gemini_summary_model.summarize(summary_prompt) == EXPECTED
    assert gemini_summary_model.model_id == "gemini-2.0-flash-exp"


async def test_gemini_summary_model_strips_code_fence(
    gemini_summary_model: SummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = f"```json\n{json.dumps(SEGMENTS)}\n```"
    assert await gemini_summary_model.summarize("Page 1 text") == EXPECTED


async def test_gemini_summary_model_empty_response(
    gemini_summary_model: SummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = ""
    assert await gemini_summary_model.summarize("Page 1 text") == SummaryResponse(
        segments=[]
    )


@pytest.mark.parametrize(
    "invalid_payload",
    [
        "not valid json",
        "{}",
        json.dumps({"segments": [{"date_range": "2023-10-27"}]}),
        json.dumps({"segments": "not-a-list"}),
    ],
)
async def test_gemini_summary_model_invalid_json(
    gemini_summary_model: SummaryModel,
    fake_gemini: FakeGeminiServer,
    invalid_payload: str,
) -> None:
    fake_gemini.text = invalid_payload
    with pytest.raises(AIError, match="Failed to parse"):
        await gemini_summary_model.summarize("Page 1 text")


async def test_gemini_summary_named_provider(
    load_gemini_models: LoadGeminiModels,
    fake_gemini: FakeGeminiServer,
    gemini_base_url: str,
) -> None:
    fake_gemini.text = json.dumps(SEGMENTS)
    _, summary, _ = await load_gemini_models(
        providers={
            "work": ProviderConfig(
                type="gemini", api_key="work-key", base_url=gemini_base_url
            )
        },
        summary=ModelConfig(provider="work", model="gemini-custom"),
    )
    assert summary is not None
    assert summary.provider == "work"
    assert summary.model_id == "gemini-custom"
    assert await summary.summarize("Page 1 text") == EXPECTED
    assert fake_gemini.requests[0][1] == "work-key"
