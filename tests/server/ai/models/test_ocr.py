"""Tests for `supernote.server.ai.models.ocr`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.ocr import ConcurrencyLimitedOcrModel, create_ocr_model
from supernote.server.config import (
    AiConfig,
    AuthConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)
from tests.server.ai.models.apple.conftest import FakeObjCModule, FakeVisionModule


def test_create_ocr_model_unconfigured(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_ocr_model(config) is None


def test_create_ocr_model_legacy_gemini() -> None:
    legacy_config = ServerConfig(gemini_api_key="test-key")
    model = create_ocr_model(legacy_config)
    assert model is not None
    assert model.model_id == "gemini-3.5-flash-lite"


def test_create_ocr_model_gemini_provider() -> None:
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
    assert ai_model is not None
    assert ai_model.model_id == "gemini-custom-ocr"


def test_create_ocr_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            ocr=ModelConfig(provider="openai", model="gemma-vision", max_concurrency=1),
        )
    )
    ai_model = create_ocr_model(ai_config)
    assert ai_model is not None
    assert ai_model.model_id == "gemma-vision"


def test_create_ocr_model_apple_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "objc", FakeObjCModule())  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "Vision", FakeVisionModule())  # type: ignore[arg-type]

    ai_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(
                provider="apple", model="vision-accurate", max_concurrency=2
            ),
        )
    )
    ai_model = create_ocr_model(ai_config)
    assert ai_model is not None
    assert ai_model.model_id == "vision-accurate"

    named_config = ServerConfig(
        ai=AiConfig(
            providers={"mac_vision": ProviderConfig(type="apple")},
            ocr=ModelConfig(
                provider="mac_vision", model="vision-fast", max_concurrency=2
            ),
        )
    )
    named_model = create_ocr_model(named_config)
    assert named_model is not None
    assert named_model.model_id == "vision-fast"

    monkeypatch.setitem(sys.modules, "Vision", None)
    with pytest.raises(AIError, match="supernote\\[apple\\]"):
        create_ocr_model(ai_config)


def test_create_ocr_model_fake_provider() -> None:
    fake_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(
                provider="fake", model="fake-ocr-custom", max_concurrency=2
            ),
        )
    )
    fake_model = create_ocr_model(fake_config)
    assert fake_model is not None
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
    with pytest.raises(
        ValueError, match="Unsupported OCR model provider type: 'unknown'"
    ):
        create_ocr_model(unsupported_config)

    named_unknown = ServerConfig(
        ai=AiConfig(
            providers={"custom": ProviderConfig(type="unknown")},
            ocr=ModelConfig(provider="custom", model="some-model"),
        )
    )
    with pytest.raises(
        ValueError, match="Unsupported OCR model provider type: 'unknown'"
    ):
        create_ocr_model(named_unknown)


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
