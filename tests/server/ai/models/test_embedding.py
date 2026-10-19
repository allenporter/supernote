"""Tests for `supernote.server.ai.models.embedding`."""

from __future__ import annotations

import pytest

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
)
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel


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
