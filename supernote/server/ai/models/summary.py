"""Notebook summarization model interface, telemetry, and concurrency wrappers.

Summary models synthesize multi-page notebook transcripts into structured,
date-grouped `SummaryResponse` segments with extracted ISO dates and page
citations. Callers assemble the full transcript prompt via
`format_summary_prompt` and pass it to `SummaryModel.summarize`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from supernote.server.ai.prompts import SummaryResponse
from supernote.server.metrics import AIStage, init_ai_metrics, track_ai_request

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "ConcurrencyLimitedSummaryModel",
    "InstrumentedSummaryModel",
    "SummaryModel",
    "create_summary_model",
]


class SummaryModel(ABC):
    """Abstract interface for a notebook-summarization model."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Identifier of the configured AI provider serving this model."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying summary model."""

    @abstractmethod
    async def summarize(
        self,
        prompt: str,
    ) -> SummaryResponse:
        """Generate structured summary segments from a formatted prompt."""


class InstrumentedSummaryModel(SummaryModel):
    """Wraps a `SummaryModel` to record Prometheus request and latency metrics."""

    def __init__(self, model: SummaryModel) -> None:
        self._model = model
        init_ai_metrics(
            provider=model.provider,
            model=model.model_id,
            stage=AIStage.SUMMARY,
        )

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def summarize(self, prompt: str) -> SummaryResponse:
        with track_ai_request(
            provider=self.provider,
            model=self.model_id,
            stage=AIStage.SUMMARY,
        ):
            return await self._model.summarize(prompt)


class ConcurrencyLimitedSummaryModel(SummaryModel):
    """Wraps a `SummaryModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: SummaryModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def summarize(self, prompt: str) -> SummaryResponse:
        async with self._semaphore:
            return await self._model.summarize(prompt)


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create the configured `SummaryModel` wrapped with telemetry and concurrency limiting.

    Wrapper order matters: `ConcurrencyLimitedSummaryModel` is outermost so
    semaphore queue wait is excluded from `InstrumentedSummaryModel` latency.
    """
    model_cfg = config.ai.summary
    if model_cfg is None:
        return None

    model: SummaryModel | None
    provider_type = config.ai.provider_type(model_cfg.provider)
    if provider_type == "gemini":
        from supernote.server.ai.models.gemini.summary import (  # noqa: PLC0415
            create_summary_model as create_gemini_summary_model,
        )

        model = create_gemini_summary_model(config)
    elif provider_type == "openai":
        from supernote.server.ai.models.openai.summary import (  # noqa: PLC0415
            create_summary_model as create_openai_summary_model,
        )

        model = create_openai_summary_model(config)
    elif provider_type == "fake":
        from supernote.server.ai.models.fake.summary import (  # noqa: PLC0415
            create_summary_model as create_fake_summary_model,
        )

        model = create_fake_summary_model(config)
    else:
        raise ValueError(f"Unsupported summary model provider type: {provider_type!r}")

    if model is None:
        return None
    return ConcurrencyLimitedSummaryModel(
        InstrumentedSummaryModel(model),
        max_concurrency=model_cfg.max_concurrency,
    )
