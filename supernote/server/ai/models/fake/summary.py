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

    def __init__(self, segments: list[SummarySegment] | None = None) -> None:
        self._segments = segments
        self.calls: list[str] = []

    @property
    def model_id(self) -> str:
        return "fake-summary-v1"

    async def summarize(
        self,
        prompt: str,
    ) -> SummaryResponse:
        self.calls.append(prompt)
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


def create_summary_model(_config: ServerConfig) -> SummaryModel:
    """Create a `FakeSummaryModel`."""
    return FakeSummaryModel()
