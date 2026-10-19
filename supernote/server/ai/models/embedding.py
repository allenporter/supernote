"""Text embedding model interface and concurrency wrapper.

An embedding model maps text into a fixed-length vector of floating-point
numbers representing its semantic meaning, allowing notebook pages and search
queries to be compared by cosine similarity. `EmbeddingModel.embed` guarantees
that returned vectors are non-empty and have a non-zero norm.
"""

from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from enum import StrEnum

__all__ = [
    "ConcurrencyLimitedEmbeddingModel",
    "EmbeddingModel",
    "EmbeddingTaskType",
]


class EmbeddingTaskType(StrEnum):
    """Task type hint for asymmetric embedding models."""

    RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
    RETRIEVAL_QUERY = "RETRIEVAL_QUERY"


class EmbeddingModel(ABC):
    """Abstract interface for a text-embedding model."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying embedding model."""

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        """Generate a validated, non-zero embedding vector for `text`."""
        values = await self._embed(text, task_type=task_type)
        norm_sq = sum(float(v) * float(v) for v in values)
        if not values or math.isclose(norm_sq, 0.0, abs_tol=1e-12):
            raise ValueError(
                f"Embedding model {self.model_id!r} returned an empty or zero-norm vector"
            )
        return [float(v) for v in values]

    @abstractmethod
    async def _embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        """Provider-specific implementation returning raw embedding values."""


class ConcurrencyLimitedEmbeddingModel(EmbeddingModel):
    """Wraps an `EmbeddingModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: EmbeddingModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def _embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        async with self._semaphore:
            return await self._model._embed(text, task_type=task_type)
