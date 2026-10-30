"""Tests for `supernote.server.ai.models.summary`."""

from __future__ import annotations

from pathlib import Path

import pytest

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    create_embedding_model,
)
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.openai.embedding import OpenAIEmbeddingModel
from supernote.server.ai.models.openai.summary import OpenAISummaryModel
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
    legacy_config = ServerConfig(gemini_api_key="test-key")
    model = create_summary_model(legacy_config)
    assert model is not None
    assert model.model_id == legacy_config.gemini_ocr_model


def test_create_summary_model_gemini_provider() -> None:
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
    assert ai_model is not None
    assert ai_model.model_id == "gemini-custom-summary"


def test_create_summary_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            summary=ModelConfig(provider="openai", model="gemma", max_concurrency=1),
        )
    )
    ai_model = create_summary_model(ai_config)
    assert ai_model is not None
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
    assert fake_model is not None
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


def test_create_summary_model_named_openai_providers() -> None:
    """Summary and embedding can use two different OpenAI-compatible servers."""
    config = ServerConfig(
        ai=AiConfig(
            providers={
                "ollama": ProviderConfig(
                    type="openai", base_url="http://localhost:11434/v1"
                ),
                "llamacpp": ProviderConfig(
                    type="openai", base_url="http://localhost:8080/v1"
                ),
            },
            summary=ModelConfig(provider="ollama", model="gemma3:27b"),
            embedding=ModelConfig(provider="llamacpp", model="embeddinggemma"),
        )
    )
    model = create_summary_model(config)
    assert isinstance(model, ConcurrencyLimitedSummaryModel)
    assert isinstance(model._model, OpenAISummaryModel)
    assert model._model._backend._base_url == "http://localhost:11434/v1"

    embedding = create_embedding_model(config)
    assert isinstance(embedding, ConcurrencyLimitedEmbeddingModel)
    assert isinstance(embedding._model, OpenAIEmbeddingModel)
    assert embedding._model._backend._base_url == "http://localhost:8080/v1"


def test_create_summary_model_unknown_provider_type() -> None:
    config = ServerConfig(
        ai=AiConfig(
            providers={"mine": ProviderConfig(type="unknown")},
            summary=ModelConfig(provider="mine", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="provider type: 'unknown'"):
        create_summary_model(config)
