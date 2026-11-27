"""Tests for `supernote.server.components.openai.embedding`."""

from __future__ import annotations

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType

from .conftest import FakeOpenAIServer


async def test_openai_embedding_model(
    openai_embedding_model: EmbeddingModel, fake_openai: FakeOpenAIServer
) -> None:
    for task_type in EmbeddingTaskType:
        assert await openai_embedding_model.embed("some text", task_type) == [
            0.1,
            0.2,
            0.3,
        ]

    assert openai_embedding_model.provider == "openai"
    assert openai_embedding_model.model_id == "nomic-embed-text"
    assert fake_openai.requests == [
        (
            "/v1/embeddings",
            "",
            {"model": "nomic-embed-text", "input": "some text"},
        )
    ] * len(EmbeddingTaskType)


async def test_openai_embedding_model_empty_vector_raises_ai_error(
    openai_embedding_model: EmbeddingModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.embedding = []
    with pytest.raises(AIError):
        await openai_embedding_model.embed(
            "some text", EmbeddingTaskType.RETRIEVAL_DOCUMENT
        )
