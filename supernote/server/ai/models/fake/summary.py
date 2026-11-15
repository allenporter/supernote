"""Fake summary model for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import SummaryResponse, SummarySegment

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "FakeSummaryModel",
    "create_summary_model",
]


class FakeSummaryModel(SummaryModel):
    """Fake summary model returning deterministic or configured `SummaryResponse`."""

    def __init__(
        self,
        segments: list[SummarySegment] | None = None,
        model_id: str = "fake-summary-v1",
        error: Exception | None = None,
        provider: str = "fake",
    ) -> None:
        self._segments = segments
        self._model_id = model_id
        self.error = error
        self._provider = provider
        self.calls: list[str] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    async def summarize(
        self,
        prompt: str,
    ) -> SummaryResponse:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        if self._segments is not None:
            return SummaryResponse(segments=list(self._segments))
        return SummaryResponse(
            segments=[
                SummarySegment(
                    date_range="2023-10-27",
                    summary=f"Summary of ({len(prompt)} chars)",
                    extracted_dates=["2023-10-27"],
                    page_refs=[1],
                )
            ]
        )


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create a `FakeSummaryModel` from `ServerConfig`, or `None` if unconfigured."""
    if config.ai.summary is None:
        return None
    return FakeSummaryModel(
        model_id=config.ai.summary.model,
        provider=config.ai.summary.provider,
    )
