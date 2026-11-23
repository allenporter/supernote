"""Text embedding model interface, validation, telemetry, and concurrency wrappers.

An embedding model maps text into a fixed-length vector of floating-point
numbers representing its semantic meaning, allowing notebook pages and search
queries to be compared by cosine similarity. Models built by
`AiRegistrar.create_embedding_model` are wrapped in `ValidatingEmbeddingModel`,
which guarantees that returned vectors are non-empty and have a finite non-zero norm.
"""

from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum

from supernote.server.ai.base import AIError
from supernote.server.metrics import AIStage, init_ai_metrics, track_ai_request

__all__ = [
    "ConcurrencyLimitedEmbeddingModel",
    "EmbeddingModel",
    "EmbeddingTaskType",
    "InstrumentedEmbeddingModel",
    "ValidatingEmbeddingModel",
    "validate_embedding_vector",
]


class EmbeddingTaskType(StrEnum):
    """Task type hint for asymmetric embedding models."""

    RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
    RETRIEVAL_QUERY = "RETRIEVAL_QUERY"


def validate_embedding_vector(
    values: Sequence[float],
    model_id: str,
) -> list[float]:
    """Return `values` as `list[float]` or raise `AIError` if empty, non-finite, or zero-norm."""
    norm_sq = sum(float(v) * float(v) for v in values)
    if (
        not values
        or not math.isfinite(norm_sq)
        or math.isclose(norm_sq, 0.0, abs_tol=1e-12)
    ):
        raise AIError(
            f"Embedding model {model_id!r} returned an empty, non-finite, or zero-norm vector"
        )
    return [float(v) for v in values]


class EmbeddingModel(ABC):
    """Abstract interface for a text-embedding model."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Identifier of the configured AI provider serving this model."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying embedding model."""

    @abstractmethod
    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        """Generate a validated, non-zero embedding vector for `text`."""


class ValidatingEmbeddingModel(EmbeddingModel):
    """Wraps an `EmbeddingModel` to reject empty, non-finite, or zero-norm vectors."""

    def __init__(self, model: EmbeddingModel) -> None:
        self._model = model

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        values = await self._model.embed(text, task_type=task_type)
        return validate_embedding_vector(values, self.model_id)


class InstrumentedEmbeddingModel(EmbeddingModel):
    """Wraps an `EmbeddingModel` to record Prometheus request and latency metrics."""

    def __init__(self, model: EmbeddingModel) -> None:
        self._model = model
        for stage in (AIStage.EMBEDDING_DOCUMENT, AIStage.EMBEDDING_QUERY):
            init_ai_metrics(
                provider=model.provider,
                model=model.model_id,
                stage=stage,
            )

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        stage = (
            AIStage.EMBEDDING_QUERY
            if task_type == EmbeddingTaskType.RETRIEVAL_QUERY
            else AIStage.EMBEDDING_DOCUMENT
        )
        with track_ai_request(
            provider=self.provider,
            model=self.model_id,
            stage=stage,
        ):
            return await self._model.embed(text, task_type=task_type)


class ConcurrencyLimitedEmbeddingModel(EmbeddingModel):
    """Wraps an `EmbeddingModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: EmbeddingModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        async with self._semaphore:
            return await self._model.embed(text, task_type=task_type)
