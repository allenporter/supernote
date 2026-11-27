"""Fake summary model for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import SummaryResponse, SummarySegment

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "FakeSummaryModel",
    "async_setup_summary",
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


async def async_setup_summary(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``fake_ai`` summary provider with `AiRegistrar`."""
    registrar.register_summary(
        "fake_ai",
        lambda provider, model: FakeSummaryModel(model_id=model, provider=provider),
    )
