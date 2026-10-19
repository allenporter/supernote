"""Tests for `supernote.server.ai.models.summary`."""

from __future__ import annotations

from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.summary import ConcurrencyLimitedSummaryModel


async def test_concurrency_limited_summary_model() -> None:
    wrapped = ConcurrencyLimitedSummaryModel(FakeSummaryModel(), max_concurrency=2)
    result = await wrapped.summarize("TRANSCRIPT:\nHello")
    assert wrapped.model_id == "fake-summary-v1"
    assert len(result.segments) == 1
