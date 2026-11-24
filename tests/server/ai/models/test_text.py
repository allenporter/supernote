"""Tests for `supernote.server.ai.models.text`."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.text import (
    ConcurrencyLimitedTextGenerationModel,
    InstrumentedTextGenerationModel,
    TextGenerationModel,
    parse_json_object,
)
from supernote.server.metrics import AIStage


class _StubTextModel(TextGenerationModel):
    def __init__(self, delay: float = 0.0) -> None:
        self._delay = delay
        self.active = 0
        self.max_active = 0
        self.calls: list[AIStage] = []

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_id(self) -> str:
        return "stub-text-v1"

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        _ = (prompt, response_schema, schema_name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append(stage)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            return {"ok": True}
        finally:
            self.active -= 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"nested": [1, 2]}\n```', {"nested": [1, 2]}),
    ],
)
def test_parse_json_object_valid(raw: str, expected: dict[str, Any]) -> None:
    assert parse_json_object(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "not json", "[1, 2]", '"str"'])
def test_parse_json_object_invalid(raw: str | None) -> None:
    with pytest.raises(AIError):
        parse_json_object(raw)


async def test_instrumented_and_concurrency_limited_text_model() -> None:
    stub = _StubTextModel(delay=0.02)
    wrapped = ConcurrencyLimitedTextGenerationModel(
        InstrumentedTextGenerationModel(stub),
        max_concurrency=2,
    )
    assert wrapped.provider == "stub"
    assert wrapped.model_id == "stub-text-v1"

    results = await asyncio.gather(
        *[
            wrapped.generate_json(
                f"prompt-{i}",
                response_schema={"type": "object"},
                stage=AIStage.WIKI_COMPILE,
            )
            for i in range(4)
        ]
    )
    assert results == [{"ok": True}] * 4
    assert stub.max_active <= 2
    assert stub.calls == [AIStage.WIKI_COMPILE] * 4
