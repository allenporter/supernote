"""Tests for `supernote.server.ai.models.openai.summary`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.openai.backend import OpenAIBackend
from supernote.server.ai.models.openai.summary import (
    OpenAISummaryModel,
    create_summary_model,
)
from supernote.server.ai.prompts import (
    SummaryResponse,
    SummarySegment,
    get_summary_json_schema,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeOpenAIServer

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
def summary_model(openai_backend: OpenAIBackend) -> OpenAISummaryModel:
    return OpenAISummaryModel(openai_backend, "gemma")


async def test_openai_summary_model(
    summary_model: OpenAISummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = json.dumps(SEGMENTS)

    assert await summary_model.summarize("Summarize this.") == EXPECTED
    assert summary_model.model_id == "gemma"
    (_, _, payload) = fake_openai.requests[0]
    assert payload == {
        "model": "gemma",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Summarize this."}]}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "summary_response",
                "schema": get_summary_json_schema(),
            },
        },
    }


async def test_openai_summary_model_strips_code_fence(
    summary_model: OpenAISummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = f"```json\n{json.dumps(SEGMENTS)}\n```"
    assert await summary_model.summarize("Summarize this.") == EXPECTED


async def test_openai_summary_model_empty_response(
    summary_model: OpenAISummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = ""
    assert await summary_model.summarize("Summarize this.") == SummaryResponse(
        segments=[]
    )


async def test_openai_summary_model_invalid_json(
    summary_model: OpenAISummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = "not valid json"
    with pytest.raises(AIError, match="Failed to parse OpenAI-compatible summary"):
        await summary_model.summarize("Summarize this.")


def test_create_summary_model() -> None:
    assert create_summary_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost/v1")},
            summary=ModelConfig(provider="openai", model="gemma"),
        )
    )
    model = create_summary_model(config)
    assert isinstance(model, OpenAISummaryModel)
    assert model.model_id == "gemma"
