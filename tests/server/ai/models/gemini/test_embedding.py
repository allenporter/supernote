"""Tests for `supernote.server.ai.models.gemini.embedding`."""

from __future__ import annotations

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.embedding import (
    GeminiEmbeddingModel,
    create_embedding_model,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeGeminiServer


async def test_gemini_embedding_model(
    gemini_backend: GeminiBackend,
    fake_gemini: FakeGeminiServer,
) -> None:
    embedding_model = GeminiEmbeddingModel(gemini_backend, "text-embedding-004")

    vec = await embedding_model.embed(
        "This is the text to embed.",
        task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT,
    )
    assert vec == [0.1, 0.2, 0.3]
    assert len(fake_gemini.requests) == 1
    path, api_key, payload = fake_gemini.requests[0]
    assert path == "/v1beta/models/text-embedding-004:batchEmbedContents"
    assert api_key == "test-key"
    assert payload == {
        "requests": [
            {
                "content": {
                    "parts": [{"text": "This is the text to embed."}],
                    "role": "user",
                },
                "model": "models/text-embedding-004",
                "taskType": "RETRIEVAL_DOCUMENT",
            }
        ]
    }

    fake_gemini.embedding = None
    with pytest.raises(AIError, match="No embeddings returned from Gemini API"):
        await embedding_model.embed(
            "This is the text to embed.",
            task_type=EmbeddingTaskType.RETRIEVAL_QUERY,
        )


def test_create_embedding_model() -> None:
    assert create_embedding_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"work": ProviderConfig(type="gemini", api_key="work-key")},
            embedding=ModelConfig(provider="work", model="gemini-custom"),
        )
    )
    model = create_embedding_model(config)
    assert isinstance(model, GeminiEmbeddingModel)
    assert model.model_id == "gemini-custom"
