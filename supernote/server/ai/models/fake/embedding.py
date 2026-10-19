"""Fake embedding model for testing."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "FakeEmbeddingModel",
    "create_embedding_model",
]


class FakeEmbeddingModel(EmbeddingModel):
    """Fake embedding model returning deterministic vectors."""

    def __init__(self, dimensions: int = 3) -> None:
        self.dimensions = dimensions
        self.calls: list[tuple[str, EmbeddingTaskType]] = []

    @property
    def model_id(self) -> str:
        return "fake-embedding-v1"

    async def _embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        self.calls.append((text, task_type))
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [
            float(digest[i % len(digest)] + 1) / 256.0 for i in range(self.dimensions)
        ]


def create_embedding_model(_config: ServerConfig) -> EmbeddingModel:
    """Create a `FakeEmbeddingModel`."""
    return FakeEmbeddingModel()
