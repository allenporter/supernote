"""Tests for `supernote.server.ai.models.embedding`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
    create_embedding_model,
)
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.config import (
    AiConfig,
    AuthConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)


def test_create_embedding_model_unconfigured(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_embedding_model(config) is None


def test_create_embedding_model_legacy_gemini() -> None:
    with patch("google.genai.Client"):
        legacy_config = ServerConfig(gemini_api_key="test-key")
        model = create_embedding_model(legacy_config)
        assert isinstance(model, ConcurrencyLimitedEmbeddingModel)
        assert model.model_id == legacy_config.gemini_embedding_model


def test_create_embedding_model_gemini_provider() -> None:
    with patch("google.genai.Client"):
        ai_config = ServerConfig(
            ai=AiConfig(
                providers={"gemini": ProviderConfig(api_key="ai-key")},
                embedding=ModelConfig(
                    provider="gemini",
                    model="gemini-custom-embed",
                    max_concurrency=6,
                ),
            )
        )
        ai_model = create_embedding_model(ai_config)
        assert isinstance(ai_model, ConcurrencyLimitedEmbeddingModel)
        assert ai_model.model_id == "gemini-custom-embed"


def test_create_embedding_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            embedding=ModelConfig(
                provider="openai", model="nomic-embed-text", max_concurrency=1
            ),
        )
    )
    ai_model = create_embedding_model(ai_config)
    assert isinstance(ai_model, ConcurrencyLimitedEmbeddingModel)
    assert ai_model.model_id == "nomic-embed-text"


def test_create_embedding_model_fake_provider() -> None:
    fake_config = ServerConfig(
        ai=AiConfig(
            embedding=ModelConfig(
                provider="fake", model="fake-embed-custom", max_concurrency=2
            ),
        )
    )
    fake_model = create_embedding_model(fake_config)
    assert isinstance(fake_model, ConcurrencyLimitedEmbeddingModel)
    assert fake_model.model_id == "fake-embed-custom"


def test_create_embedding_model_missing_provider_credentials() -> None:
    missing_provider_config = ServerConfig(
        ai=AiConfig(
            embedding=ModelConfig(provider="gemini", model="gemini-embedding-001"),
        )
    )
    assert create_embedding_model(missing_provider_config) is None


def test_create_embedding_model_unsupported_provider() -> None:
    unsupported_config = ServerConfig(
        ai=AiConfig(
            embedding=ModelConfig(provider="unknown", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="Unsupported embedding model provider"):
        create_embedding_model(unsupported_config)


async def test_concurrency_limited_embedding_model() -> None:
    fake = FakeEmbeddingModel()
    wrapped = ConcurrencyLimitedEmbeddingModel(fake, max_concurrency=2)
    assert wrapped.model_id == "fake-embedding-v1"
    vec = await wrapped.embed("hello", task_type=EmbeddingTaskType.RETRIEVAL_QUERY)
    assert len(vec) == 3
    assert fake.calls == [("hello", EmbeddingTaskType.RETRIEVAL_QUERY)]


async def test_embedding_model_rejects_empty_and_zero_norm_vectors() -> None:
    empty_model = FakeEmbeddingModel(dimensions=0)
    with pytest.raises(ValueError, match="empty or zero-norm"):
        await empty_model.embed("hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)

    class ZeroEmbeddingModel(FakeEmbeddingModel):
        async def _embed(
            self,
            text: str,
            task_type: EmbeddingTaskType,
        ) -> list[float]:
            return [0.0, 0.0, 0.0]

    zero_model = ZeroEmbeddingModel()
    with pytest.raises(ValueError, match="empty or zero-norm"):
        await zero_model.embed("hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)
