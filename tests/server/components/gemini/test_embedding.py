"""Tests for `supernote.server.components.gemini.embedding`."""

from __future__ import annotations

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.config import ModelConfig, ProviderConfig

from .conftest import FakeGeminiServer, LoadGeminiModels


async def test_gemini_embedding_model(
    gemini_embedding_model: EmbeddingModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    vec = await gemini_embedding_model.embed(
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
        await gemini_embedding_model.embed(
            "This is the text to embed.",
            task_type=EmbeddingTaskType.RETRIEVAL_QUERY,
        )


async def test_gemini_embedding_named_provider(
    load_gemini_models: LoadGeminiModels,
    fake_gemini: FakeGeminiServer,
    gemini_base_url: str,
) -> None:
    _, _, embedding = await load_gemini_models(
        providers={
            "work": ProviderConfig(
                type="gemini", api_key="work-key", base_url=gemini_base_url
            )
        },
        embedding=ModelConfig(provider="work", model="gemini-custom"),
    )
    assert embedding is not None
    assert embedding.provider == "work"
    assert embedding.model_id == "gemini-custom"
    assert await embedding.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY) == [
        0.1,
        0.2,
        0.3,
    ]
    assert fake_gemini.requests[0][1] == "work-key"
