"""Tests for `supernote.server.components.fake_ai.summary`."""

from __future__ import annotations

from supernote.server.ai.prompts import SummarySegment
from supernote.server.components.fake_ai.summary import FakeSummaryModel


async def test_fake_summary_model() -> None:
    summary_model = FakeSummaryModel(
        segments=[
            SummarySegment(
                date_range="2026-10-18",
                summary="- Done",
                extracted_dates=["2026-10-18"],
                page_refs=[1],
            )
        ]
    )
    summary = await summary_model.summarize("TRANSCRIPT:\ntranscript")
    assert len(summary.segments) == 1
    assert summary.segments[0].date_range == "2026-10-18"
    assert summary_model.model_id == "fake-summary-v1"
