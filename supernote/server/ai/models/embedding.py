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
from typing import TYPE_CHECKING

from supernote.server.ai.base import AIError

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "ConcurrencyLimitedEmbeddingModel",
    "EmbeddingModel",
    "EmbeddingTaskType",
    "create_embedding_model",
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
        if (
            not values
            or not math.isfinite(norm_sq)
            or math.isclose(norm_sq, 0.0, abs_tol=1e-12)
        ):
            raise AIError(
                f"Embedding model {self.model_id!r} returned an empty, non-finite, or zero-norm vector"
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


def create_embedding_model(config: ServerConfig) -> EmbeddingModel | None:
    """Create the configured `EmbeddingModel` wrapped with concurrency limiting."""
    model_cfg = config.ai.embedding
    if model_cfg is None:
        return None

    model: EmbeddingModel | None
    provider_type = config.ai.provider_type(model_cfg.provider)
    if provider_type == "gemini":
        from supernote.server.ai.models.gemini.embedding import (  # noqa: PLC0415
            create_embedding_model as create_gemini_embedding_model,
        )

        model = create_gemini_embedding_model(config)
    elif provider_type == "openai":
        from supernote.server.ai.models.openai.embedding import (  # noqa: PLC0415
            create_embedding_model as create_openai_embedding_model,
        )

        model = create_openai_embedding_model(config)
    elif provider_type == "fake":
        from supernote.server.ai.models.fake.embedding import (  # noqa: PLC0415
            create_embedding_model as create_fake_embedding_model,
        )

        model = create_fake_embedding_model(config)
    else:
        raise ValueError(
            f"Unsupported embedding model provider type: {provider_type!r}"
        )

    if model is None:
        return None
    return ConcurrencyLimitedEmbeddingModel(
        model, max_concurrency=model_cfg.max_concurrency
    )
