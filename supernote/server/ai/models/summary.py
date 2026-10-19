"""Notebook summarization model interface and concurrency wrapper.

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

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "ConcurrencyLimitedSummaryModel",
    "SummaryModel",
    "create_summary_model",
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


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create the configured `SummaryModel` wrapped with concurrency limiting."""
    if not config.gemini_api_key or not config.gemini_api_key.strip():
        return None

    from supernote.server.ai.models.gemini.summary import (  # noqa: PLC0415
        create_summary_model as create_gemini_summary_model,
    )

    model = create_gemini_summary_model(config)
    if model is None:
        return None
    # TODO(#301): Generalize `gemini_max_concurrency` across AI providers.
    return ConcurrencyLimitedSummaryModel(
        model, max_concurrency=config.gemini_max_concurrency
    )
