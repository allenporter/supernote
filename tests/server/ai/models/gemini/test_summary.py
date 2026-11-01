"""Tests for `supernote.server.ai.models.gemini.summary`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.summary import (
    GeminiSummaryModel,
    create_summary_model,
)
from supernote.server.ai.prompts import (
    SummaryResponse,
    SummarySegment,
    format_summary_prompt,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeGeminiServer

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


@pytest.fixture
def summary_model(gemini_backend: GeminiBackend) -> GeminiSummaryModel:
    return GeminiSummaryModel(gemini_backend, "gemini-2.0-flash-exp")


async def test_gemini_summary_model(
    summary_model: GeminiSummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = json.dumps(SEGMENTS)

    summary_prompt = format_summary_prompt("Page 1 text", custom_type="real")
    assert await summary_model.summarize(summary_prompt) == EXPECTED
    assert summary_model.model_id == "gemini-2.0-flash-exp"


async def test_gemini_summary_model_strips_code_fence(
    summary_model: GeminiSummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = f"```json\n{json.dumps(SEGMENTS)}\n```"
    assert await summary_model.summarize("Page 1 text") == EXPECTED


async def test_gemini_summary_model_empty_response(
    summary_model: GeminiSummaryModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.text = ""
    assert await summary_model.summarize("Page 1 text") == SummaryResponse(segments=[])


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
    summary_model: GeminiSummaryModel,
    fake_gemini: FakeGeminiServer,
    invalid_payload: str,
) -> None:
    fake_gemini.text = invalid_payload
    with pytest.raises(AIError, match="Failed to parse"):
        await summary_model.summarize("Page 1 text")


def test_create_summary_model() -> None:
    assert create_summary_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"work": ProviderConfig(type="gemini", api_key="work-key")},
            summary=ModelConfig(provider="work", model="gemini-custom"),
        )
    )
    model = create_summary_model(config)
    assert isinstance(model, GeminiSummaryModel)
    assert model.model_id == "gemini-custom"
