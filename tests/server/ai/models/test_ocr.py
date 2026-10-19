"""Tests for `supernote.server.ai.models.ocr`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.ocr import ConcurrencyLimitedOcrModel, create_ocr_model
from supernote.server.config import AuthConfig, ServerConfig


def test_create_ocr_model(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_ocr_model(config) is None

    with patch("google.genai.Client"):
        config.gemini_api_key = "test-key"
        model = create_ocr_model(config)
        assert isinstance(model, ConcurrencyLimitedOcrModel)
        assert model.model_id == config.gemini_ocr_model


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
    assert wrapped.model_id == "fake-ocr-v1"
    await asyncio.gather(*[wrapped.extract_text(b"png", "prompt") for _ in range(4)])
    assert max_active_seen == 2
    assert active_calls == 0
