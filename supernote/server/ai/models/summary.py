"""Notebook summarization model interface, telemetry, and concurrency wrappers.

Summary models synthesize multi-page notebook transcripts into structured,
date-grouped `SummaryResponse` segments with extracted ISO dates and page
citations. Callers assemble the full transcript prompt via
`format_summary_prompt` and pass it to `SummaryModel.summarize`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from supernote.server.ai.prompts import SummaryResponse
from supernote.server.metrics import AIStage, init_ai_metrics, track_ai_request

__all__ = [
    "ConcurrencyLimitedSummaryModel",
    "InstrumentedSummaryModel",
    "SummaryModel",
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
