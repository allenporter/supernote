"""Tests for `supernote.server.ai.models.ocr`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.ocr import ConcurrencyLimitedOcrModel, create_ocr_model
from supernote.server.config import (
    AiConfig,
    AuthConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)


def test_create_ocr_model_unconfigured(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_ocr_model(config) is None


def test_create_ocr_model_legacy_gemini() -> None:
    with patch("google.genai.Client"):
        legacy_config = ServerConfig(gemini_api_key="test-key")
        model = create_ocr_model(legacy_config)
        assert isinstance(model, ConcurrencyLimitedOcrModel)
        assert model.model_id == legacy_config.gemini_ocr_model


def test_create_ocr_model_gemini_provider() -> None:
    with patch("google.genai.Client"):
        ai_config = ServerConfig(
            ai=AiConfig(
                providers={"gemini": ProviderConfig(api_key="ai-key")},
                ocr=ModelConfig(
                    provider="gemini",
                    model="gemini-custom-ocr",
                    max_concurrency=3,
                ),
            )
        )
        ai_model = create_ocr_model(ai_config)
        assert isinstance(ai_model, ConcurrencyLimitedOcrModel)
        assert ai_model.model_id == "gemini-custom-ocr"


def test_create_ocr_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            ocr=ModelConfig(provider="openai", model="gemma-vision", max_concurrency=1),
        )
    )
    ai_model = create_ocr_model(ai_config)
    assert isinstance(ai_model, ConcurrencyLimitedOcrModel)
    assert ai_model.model_id == "gemma-vision"


def test_create_ocr_model_fake_provider() -> None:
    fake_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(
                provider="fake", model="fake-ocr-custom", max_concurrency=2
            ),
        )
    )
    fake_model = create_ocr_model(fake_config)
    assert isinstance(fake_model, ConcurrencyLimitedOcrModel)
    assert fake_model.model_id == "fake-ocr-custom"


def test_create_ocr_model_missing_provider_credentials() -> None:
    missing_provider_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(provider="gemini", model="gemini-3.6-flash"),
        )
    )
    assert create_ocr_model(missing_provider_config) is None


def test_create_ocr_model_unsupported_provider() -> None:
    unsupported_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(provider="unknown", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="Unsupported OCR model provider"):
        create_ocr_model(unsupported_config)


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
