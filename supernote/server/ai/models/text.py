"""Provider-neutral structured JSON text generation model interface and wrappers.

Defines `TextGenerationModel` for general structured LLM tasks (such as LLM Wiki
compilation and semantic lint) decoupled from `SummaryModel`, together with
`InstrumentedTextGenerationModel` (Prometheus telemetry) and
`ConcurrencyLimitedTextGenerationModel` (bounded in-flight concurrency).
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from supernote.server.ai.base import AIError
from supernote.server.metrics import AIStage, init_ai_metrics, track_ai_request

__all__ = [
    "ConcurrencyLimitedTextGenerationModel",
    "InstrumentedTextGenerationModel",
    "TextGenerationModel",
    "parse_json_object",
]

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(?P<body>.*?)\n\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def parse_json_object(raw_text: str | None) -> dict[str, Any]:
    """Parse a JSON object returned by an LLM, stripping optional Markdown fences.

    Raises `AIError` when the response is empty, malformed JSON, or not a JSON
    object (`dict`).
    """
    if not raw_text or not raw_text.strip():
        raise AIError("Text generation model returned an empty response")
    cleaned = raw_text.strip()
    if match := _JSON_FENCE_RE.match(cleaned):
        cleaned = match.group("body").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise AIError(f"Text generation model returned invalid JSON: {err}") from err
    if not isinstance(parsed, dict):
        raise AIError(
            f"Text generation model returned {type(parsed).__name__}, expected JSON object"
        )
    return parsed


class TextGenerationModel(ABC):
    """Abstract interface for provider-neutral structured JSON text generation."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Identifier of the configured AI provider serving this model."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying text generation model."""

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        """Generate a structured JSON object conforming to ``response_schema``."""


class InstrumentedTextGenerationModel(TextGenerationModel):
    """Wraps a `TextGenerationModel` to record Prometheus request and latency metrics."""

    def __init__(self, model: TextGenerationModel) -> None:
        self._model = model
        self._initialized_stages: set[AIStage] = {AIStage.TEXT}
        init_ai_metrics(
            provider=model.provider,
            model=model.model_id,
            stage=AIStage.TEXT,
        )

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        if stage not in self._initialized_stages:
            init_ai_metrics(provider=self.provider, model=self.model_id, stage=stage)
            self._initialized_stages.add(stage)
        with track_ai_request(
            provider=self.provider,
            model=self.model_id,
            stage=stage,
        ):
            return await self._model.generate_json(
                prompt,
                response_schema=response_schema,
                schema_name=schema_name,
                stage=stage,
            )


class ConcurrencyLimitedTextGenerationModel(TextGenerationModel):
    """Wraps a `TextGenerationModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: TextGenerationModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        async with self._semaphore:
            return await self._model.generate_json(
                prompt,
                response_schema=response_schema,
                schema_name=schema_name,
                stage=stage,
            )
