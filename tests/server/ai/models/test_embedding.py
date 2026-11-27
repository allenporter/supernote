"""Tests for `supernote.server.ai.models.embedding` wrappers."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
    InstrumentedEmbeddingModel,
    ValidatingEmbeddingModel,
)
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel


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


async def test_direct_fake_embedding_model_enforces_validation() -> None:
    with pytest.raises(AIError, match="empty, non-finite, or zero-norm"):
        await FakeEmbeddingModel(dimensions=0).embed(
            "hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
        )
