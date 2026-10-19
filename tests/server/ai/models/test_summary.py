"""Tests for `supernote.server.ai.models.summary`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    create_summary_model,
)
from supernote.server.config import (
    AiConfig,
    AuthConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)


def test_create_summary_model_unconfigured(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_summary_model(config) is None


def test_create_summary_model_legacy_gemini() -> None:
    with patch("google.genai.Client"):
        legacy_config = ServerConfig(gemini_api_key="test-key")
        model = create_summary_model(legacy_config)
        assert isinstance(model, ConcurrencyLimitedSummaryModel)
        assert model.model_id == legacy_config.gemini_ocr_model


def test_create_summary_model_gemini_provider() -> None:
    with patch("google.genai.Client"):
        ai_config = ServerConfig(
            ai=AiConfig(
                providers={"gemini": ProviderConfig(api_key="ai-key")},
                summary=ModelConfig(
                    provider="gemini",
                    model="gemini-custom-summary",
                    max_concurrency=4,
                ),
            )
        )
        ai_model = create_summary_model(ai_config)
        assert isinstance(ai_model, ConcurrencyLimitedSummaryModel)
        assert ai_model.model_id == "gemini-custom-summary"


def test_create_summary_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            summary=ModelConfig(provider="openai", model="gemma", max_concurrency=1),
        )
    )
    ai_model = create_summary_model(ai_config)
    assert isinstance(ai_model, ConcurrencyLimitedSummaryModel)
    assert ai_model.model_id == "gemma"


def test_create_summary_model_fake_provider() -> None:
    fake_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(
                provider="fake", model="fake-summary-custom", max_concurrency=2
            ),
        )
    )
    fake_model = create_summary_model(fake_config)
    assert isinstance(fake_model, ConcurrencyLimitedSummaryModel)
    assert fake_model.model_id == "fake-summary-custom"


def test_create_summary_model_missing_provider_credentials() -> None:
    missing_provider_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(provider="gemini", model="gemini-3.6-flash"),
        )
    )
    assert create_summary_model(missing_provider_config) is None


def test_create_summary_model_unsupported_provider() -> None:
    unsupported_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(provider="unknown", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="Unsupported summary model provider"):
        create_summary_model(unsupported_config)


async def test_concurrency_limited_summary_model() -> None:
    wrapped = ConcurrencyLimitedSummaryModel(FakeSummaryModel(), max_concurrency=2)
    result = await wrapped.summarize("TRANSCRIPT:\nHello")
    assert wrapped.model_id == "fake-summary-v1"
    assert len(result.segments) == 1
