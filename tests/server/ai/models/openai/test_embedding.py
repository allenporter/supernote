"""Tests for `supernote.server.ai.models.openai.embedding`."""

from __future__ import annotations

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.openai.backend import OpenAIBackend
from supernote.server.ai.models.openai.embedding import (
    OpenAIEmbeddingModel,
    create_embedding_model,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeOpenAIServer


async def test_openai_embedding_model(
    openai_backend: OpenAIBackend, fake_openai: FakeOpenAIServer
) -> None:
    model = OpenAIEmbeddingModel(openai_backend, "nomic-embed-text")

    for task_type in EmbeddingTaskType:
        assert await model.embed("some text", task_type) == [0.1, 0.2, 0.3]

    assert model.model_id == "nomic-embed-text"
    assert fake_openai.requests == [
        (
            "/v1/embeddings",
            "",
            {"model": "nomic-embed-text", "input": "some text"},
        )
    ] * len(EmbeddingTaskType)


def test_create_embedding_model() -> None:
    assert create_embedding_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost/v1")},
            embedding=ModelConfig(provider="openai", model="nomic-embed-text"),
        )
    )
    model = create_embedding_model(config)
    assert isinstance(model, OpenAIEmbeddingModel)
    assert model.model_id == "nomic-embed-text"
