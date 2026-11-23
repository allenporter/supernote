"""Tests for `supernote.server.components.openai.summary`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import (
    SummaryResponse,
    SummarySegment,
    get_summary_json_schema,
)

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


async def test_openai_summary_model(
    openai_summary_model: SummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = json.dumps(SEGMENTS)

    assert await openai_summary_model.summarize("Summarize this.") == EXPECTED
    assert openai_summary_model.provider == "openai"
    assert openai_summary_model.model_id == "gemma"
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
    openai_summary_model: SummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = f"```json\n{json.dumps(SEGMENTS)}\n```"
    assert await openai_summary_model.summarize("Summarize this.") == EXPECTED


async def test_openai_summary_model_empty_response(
    openai_summary_model: SummaryModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = ""
    assert await openai_summary_model.summarize("Summarize this.") == SummaryResponse(
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
async def test_openai_summary_model_invalid_json(
    openai_summary_model: SummaryModel,
    fake_openai: FakeOpenAIServer,
    invalid_payload: str,
) -> None:
    fake_openai.chat_content = invalid_payload
    with pytest.raises(AIError, match="Failed to parse"):
        await openai_summary_model.summarize("Summarize this.")
