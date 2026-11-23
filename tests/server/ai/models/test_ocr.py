"""Tests for `supernote.server.ai.models.ocr` wrappers."""

from __future__ import annotations

import asyncio
import time

from prometheus_client import REGISTRY

from supernote.server.ai.models.ocr import (
    ConcurrencyLimitedOcrModel,
    InstrumentedOcrModel,
    PromptOverrideOcrModel,
)
from supernote.server.components.fake_ai.ocr import FakeOcrModel


async def test_concurrency_limited_ocr_model() -> None:
    active_calls = 0
    max_active_seen = 0

    class SlowOcrModel(FakeOcrModel):
        async def extract_text(self, png_data: bytes, prompt: str) -> str:
            nonlocal active_calls, max_active_seen
            active_calls += 1
            max_active_seen = max(max_active_seen, active_calls)
            try:
                await asyncio.sleep(0.05)
                return await super().extract_text(png_data, prompt)
            finally:
                active_calls -= 1

    wrapped = ConcurrencyLimitedOcrModel(SlowOcrModel(), max_concurrency=2)
    assert wrapped.provider == "fake"
    assert wrapped.model_id == "fake-ocr-v1"
    await asyncio.gather(*[wrapped.extract_text(b"png", "prompt") for _ in range(4)])
    assert max_active_seen == 2
    assert active_calls == 0


async def test_instrumented_concurrency_excludes_semaphore_queue_wait() -> None:
    """Verify startup series seeding and that semaphore wait is excluded from model latency."""
    call_1_inside = asyncio.Event()
    release_call_1 = asyncio.Event()
    call_count = 0
    sum_before_call_2 = 0.0

    dur_labels = {
        "provider": "fake-gated",
        "model": "gated-ocr-v1",
        "stage": "ocr",
    }
    ok_labels = {**dur_labels, "status": "success"}
    fail_labels = {**dur_labels, "status": "failure"}

    class GatedOcrModel(FakeOcrModel):
        async def extract_text(self, png_data: bytes, prompt: str) -> str:
            nonlocal call_count, sum_before_call_2
            call_count += 1
            if call_count == 1:
                call_1_inside.set()
                await release_call_1.wait()
            else:
                sum_before_call_2 = (
                    REGISTRY.get_sample_value(
                        "supernote_ai_request_duration_seconds_sum", dur_labels
                    )
                    or 0.0
                )
            return await super().extract_text(png_data, prompt)

    inner = InstrumentedOcrModel(
        GatedOcrModel(model_id="gated-ocr-v1", provider="fake-gated")
    )
    wrapped = ConcurrencyLimitedOcrModel(inner, max_concurrency=1)

    # Pre-seeded at 0 before any call runs
    before_ok = REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
    before_fail = REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
    assert before_ok is not None
    assert before_fail is not None

    task_1 = asyncio.create_task(wrapped.extract_text(b"png1", "prompt"))
    await call_1_inside.wait()

    queue_wait = 0.2
    call_2_start = time.monotonic()
    task_2 = asyncio.create_task(wrapped.extract_text(b"png2", "prompt"))
    await asyncio.sleep(queue_wait)
    release_call_1.set()

    await asyncio.gather(task_1, task_2)
    call_2_wall_time = time.monotonic() - call_2_start

    sum_after_call_2 = (
        REGISTRY.get_sample_value(
            "supernote_ai_request_duration_seconds_sum", dur_labels
        )
        or 0.0
    )
    call_2_observed_latency = sum_after_call_2 - sum_before_call_2

    assert call_2_wall_time >= queue_wait
    assert call_2_observed_latency < queue_wait / 2
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
        == before_ok + 2.0
    )


async def test_prompt_override_ocr_model() -> None:
    inner = FakeOcrModel(model_id="DeepSeek-OCR-8bit", provider="local")
    wrapped = PromptOverrideOcrModel(inner, "Convert the document to markdown.")

    assert wrapped.provider == "local"
    assert wrapped.model_id == "DeepSeek-OCR-8bit"

    result = await wrapped.extract_text(b"png-bytes", "long composed prompt")
    assert result
    assert inner.calls == [(b"png-bytes", "Convert the document to markdown.")]
