"""Tests for `supernote.server.components.fake_ai.embedding`."""

from __future__ import annotations

import math

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.fake_ai.embedding import (
    FakeEmbeddingModel,
    create_embedding_model,
)
from supernote.server.config import AiConfig, ModelConfig, ServerConfig


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


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


def test_create_fake_embedding_model_from_config() -> None:
    assert create_embedding_model(ServerConfig()) is None

    configured = ServerConfig(
        ai=AiConfig(embedding=ModelConfig(provider="fake", model="fake-embedding-v1"))
    )
    model = create_embedding_model(configured)
    assert isinstance(model, FakeEmbeddingModel)
    assert model.provider == "fake"
    assert model.model_id == "fake-embedding-v1"


async def test_fake_embedding_model_blended_token_similarity() -> None:
    """Blended mode produces graded similarity proportional to shared vocabulary."""
    model = FakeEmbeddingModel(dimensions=128, blended=True)

    query_vec = await model.embed(
        "telescope alignment", task_type=EmbeddingTaskType.RETRIEVAL_QUERY
    )
    exact_vec = await model.embed(
        "Telescope alignment", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )
    partial_vec = await model.embed(
        "Field study on telescope alignment under clear night skies",
        task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT,
    )
    disjoint_vec = await model.embed(
        "Quarterly budget spreadsheet and grocery checklist",
        task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT,
    )

    assert len(query_vec) == 128
    assert math.isclose(_cosine(query_vec, exact_vec), 1.0, rel_tol=1e-9)
    assert 0.40 < _cosine(query_vec, partial_vec) < 0.85
    assert _cosine(query_vec, partial_vec) > _cosine(query_vec, disjoint_vec) + 0.25


async def test_fake_embedding_model_blended_punctuation_fallback() -> None:
    """Blended mode falls back to raw digest when input contains no word tokens."""
    model = FakeEmbeddingModel(dimensions=8, blended=True)
    punct_vec = await model.embed("!!!", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)
    assert len(punct_vec) == 8


async def test_fake_embedding_model_blended_rejects_zero_dimensions() -> None:
    """Blended mode validates against zero-dimension configuration."""
    with pytest.raises(AIError, match="empty, non-finite, or zero-norm"):
        await FakeEmbeddingModel(dimensions=0, blended=True).embed(
            "hello", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
        )
