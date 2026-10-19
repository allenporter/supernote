"""Notebook summarization model interface and concurrency wrapper.

Summary models synthesize multi-page notebook transcripts into structured,
date-grouped `SummaryResponse` segments with extracted ISO dates and page
citations. Callers assemble the full transcript prompt via
`format_summary_prompt` and pass it to `SummaryModel.summarize`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from supernote.server.ai.prompts import SummaryResponse

__all__ = [
    "ConcurrencyLimitedSummaryModel",
    "SummaryModel",
]


class SummaryModel(ABC):
    """Abstract interface for a notebook-summarization model."""

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


class ConcurrencyLimitedSummaryModel(SummaryModel):
    """Wraps a `SummaryModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: SummaryModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def summarize(self, prompt: str) -> SummaryResponse:
        async with self._semaphore:
            return await self._model.summarize(prompt)
