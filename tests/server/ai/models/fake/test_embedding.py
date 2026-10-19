"""Tests for `supernote.server.ai.models.fake.embedding`."""

from __future__ import annotations

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel


async def test_fake_embedding_model() -> None:
    embedding_model = FakeEmbeddingModel()
    vec = await embedding_model.embed(
        "hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )
    assert len(vec) == 3
    assert vec == await embedding_model.embed(
        "hello", task_type=EmbeddingTaskType.RETRIEVAL_QUERY
    )
    assert embedding_model.calls == [
        ("hello", EmbeddingTaskType.RETRIEVAL_DOCUMENT),
        ("hello", EmbeddingTaskType.RETRIEVAL_QUERY),
    ]
