"""Tests for `supernote.server.ai.models.summary` wrappers."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    InstrumentedSummaryModel,
)
from supernote.server.components.fake_ai.summary import FakeSummaryModel


async def test_concurrency_limited_summary_model() -> None:
    wrapped = ConcurrencyLimitedSummaryModel(
        InstrumentedSummaryModel(FakeSummaryModel()), max_concurrency=2
    )
    result = await wrapped.summarize("TRANSCRIPT:\nHello")
    assert wrapped.provider == "fake"
    assert wrapped.model_id == "fake-summary-v1"
    assert len(result.segments) == 1


async def test_instrumented_summary_model_records_success_and_failure() -> None:
    model = FakeSummaryModel(model_id="instr-summary-v1", provider="fake-instr")
    wrapped = InstrumentedSummaryModel(model)
    ok_labels = {
        "provider": "fake-instr",
        "model": "instr-summary-v1",
        "stage": "summary",
        "status": "success",
    }
    fail_labels = {**ok_labels, "status": "failure"}
    before_ok = REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
    before_fail = REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
    assert before_ok is not None
    assert before_fail is not None

    await wrapped.summarize("TRANSCRIPT:\nHello")
    model.error = AIError("boom")
    with pytest.raises(AIError, match="boom"):
        await wrapped.summarize("TRANSCRIPT:\nHello")

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
        == before_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == before_fail + 1.0
    )
