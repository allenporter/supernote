"""Fake embedding model for testing."""

from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING

from supernote.server.ai.models.embedding import (
    EmbeddingModel,
    EmbeddingTaskType,
    validate_embedding_vector,
)

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = ["FakeEmbeddingModel", "async_setup_embedding", "create_embedding_model"]

_TOKEN_RE = re.compile(r"[^\W_]+")
_BLENDED_STOPWORDS = frozenset(
    "a an and are at by for from in is of on or the to under with".split()
)


def _raw_digest_vector(text: str, dimensions: int) -> list[float]:
    """Generate deterministic positive floats from the SHA-256 digest of `text`."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(digest[i % len(digest)] + 1) / 256.0 for i in range(dimensions)]


def _token_unit_vector(token: str, dimensions: int) -> list[float]:
    """Map a normalized token to a deterministic zero-mean unit vector."""
    raw: list[float] = []
    block = 0
    while len(raw) < dimensions:
        digest = hashlib.sha256(f"{token}:{block}".encode()).digest()
        for offset in range(0, len(digest), 2):
            if len(raw) < dimensions:
                u16 = (digest[offset] << 8) | digest[offset + 1]
                # Half-integer center keeps every coordinate non-zero across [-1.0, 1.0].
                raw.append((u16 - 32767.5) / 32767.5)
        block += 1

    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


def _blended_token_vector(text: str, dimensions: int) -> list[float]:
    """Sum per-token signed unit vectors and L2-normalize to blend multi-word inputs."""
    if dimensions <= 0:
        return []
    all_tokens = _TOKEN_RE.findall(text.casefold())
    if not all_tokens:
        return _raw_digest_vector(text, dimensions)
    tokens = [t for t in all_tokens if t not in _BLENDED_STOPWORDS] or all_tokens

    summed = [0.0] * dimensions
    for token in tokens:
        for i, val in enumerate(_token_unit_vector(token, dimensions)):
            summed[i] += val

    norm = math.sqrt(sum(v * v for v in summed))
    if math.isclose(norm, 0.0, abs_tol=1e-12):
        return _raw_digest_vector(text, dimensions)
    return [v / norm for v in summed]


class FakeEmbeddingModel(EmbeddingModel):
    """Fake embedding model returning deterministic whole-text or token-blended vectors."""

    def __init__(
        self,
        dimensions: int = 3,
        model_id: str = "fake-embedding-v1",
        provider: str = "fake",
        *,
        blended: bool = False,
    ) -> None:
        self.dimensions = dimensions
        self._model_id = model_id
        self._provider = provider
        self.blended = blended
        self.calls: list[tuple[str, EmbeddingTaskType]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        self.calls.append((text, task_type))
        values = (
            _blended_token_vector(text, self.dimensions)
            if self.blended
            else _raw_digest_vector(text, self.dimensions)
        )
        return validate_embedding_vector(values, self._model_id)


def create_embedding_model(config: ServerConfig) -> EmbeddingModel | None:
    """Create a `FakeEmbeddingModel` from `ServerConfig`, or `None` if unconfigured."""
    if config.ai.embedding is None:
        return None
    return FakeEmbeddingModel(
        model_id=config.ai.embedding.model,
        provider=config.ai.embedding.provider,
    )


async def async_setup_embedding(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``fake`` embedding provider with `AiRegistrar`."""
    registrar.register_embedding("fake", create_embedding_model)
