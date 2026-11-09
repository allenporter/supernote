"""Tests for `supernote.server.ai.models.embedding`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
    InstrumentedEmbeddingModel,
    ValidatingEmbeddingModel,
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
    legacy_config = ServerConfig(gemini_api_key="test-key")
    model = create_embedding_model(legacy_config)
    assert model is not None
    assert model.model_id == legacy_config.gemini_embedding_model


def test_create_embedding_model_gemini_provider() -> None:
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
    assert ai_model is not None
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
    assert ai_model is not None
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
    assert fake_model is not None
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
    wrapped = ConcurrencyLimitedEmbeddingModel(
        InstrumentedEmbeddingModel(ValidatingEmbeddingModel(fake)), max_concurrency=2
    )
    assert wrapped.provider == "fake"
    assert wrapped.model_id == "fake-embedding-v1"
    vec = await wrapped.embed("hello", task_type=EmbeddingTaskType.RETRIEVAL_QUERY)
    assert len(vec) == 3
    assert fake.calls == [("hello", EmbeddingTaskType.RETRIEVAL_QUERY)]


@pytest.mark.parametrize(
    "bad_vector",
    [
        [],
        [0.0, 0.0, 0.0],
        [float("nan"), 1.0],
        [float("inf"), 1.0],
    ],
)
async def test_embedding_model_rejects_invalid_vectors(
    bad_vector: list[float],
) -> None:
    class BadEmbeddingModel(FakeEmbeddingModel):
        async def embed(
            self,
            text: str,
            task_type: EmbeddingTaskType,
        ) -> list[float]:
            return bad_vector

    bad_model = InstrumentedEmbeddingModel(
        ValidatingEmbeddingModel(
            BadEmbeddingModel(model_id="bad-embed-v1", provider="fake-bad")
        )
    )
    fail_labels = {
        "provider": "fake-bad",
        "model": "bad-embed-v1",
        "stage": "embedding_doc",
        "status": "failure",
    }
    before_fail = REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
    assert before_fail is not None

    with pytest.raises(AIError, match="empty, non-finite, or zero-norm"):
        await bad_model.embed("hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == before_fail + 1.0
    )


async def test_direct_and_factory_embedding_models_enforce_validation(
    aiohttp_server: Any,
) -> None:
    """Both direct provider instances and `create_embedding_model` reject bad vectors."""
    with pytest.raises(AIError, match="empty, non-finite, or zero-norm"):
        await FakeEmbeddingModel(dimensions=0).embed(
            "hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
        )

    async def handle_zero_embedding(request: web.Request) -> web.Response:
        return web.json_response({"data": [{"embedding": [0.0, 0.0, 0.0]}]})

    app = web.Application()
    app.router.add_post("/v1/embeddings", handle_zero_embedding)
    server = await aiohttp_server(app)

    config = ServerConfig(
        ai=AiConfig(
            providers={
                "local-emb": ProviderConfig(
                    type="openai", base_url=str(server.make_url("/v1"))
                )
            },
            embedding=ModelConfig(provider="local-emb", model="zero-vec-model"),
        )
    )
    model = create_embedding_model(config)
    assert model is not None

    fail_labels = {
        "provider": "local-emb",
        "model": "zero-vec-model",
        "stage": "embedding_query",
        "status": "failure",
    }
    before_fail = REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
    assert before_fail is not None

    with pytest.raises(AIError, match="empty, non-finite, or zero-norm"):
        await model.embed("query", task_type=EmbeddingTaskType.RETRIEVAL_QUERY)

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == before_fail + 1.0
    )
