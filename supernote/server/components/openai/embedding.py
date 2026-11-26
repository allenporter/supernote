"""OpenAI-compatible text embedding model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.embedding import (
    EmbeddingModel,
    EmbeddingTaskType,
    validate_embedding_vector,
)

from . import resolve_openai_backend
from .backend import OpenAIBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "OpenAIEmbeddingModel",
    "async_setup_embedding",
]


class OpenAIEmbeddingModel(EmbeddingModel):
    """OpenAI-compatible text embedding model.

    The OpenAI `/embeddings` API has no task-type hint, so documents and
    queries are embedded the same way.
    """

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return self._backend.provider

    @property
    def model_id(self) -> str:
        return self._model_name

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        values = await self._backend.embeddings(model=self._model_name, text=text)
        return validate_embedding_vector(values, self._model_name)


async def async_setup_embedding(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``openai`` embedding provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> EmbeddingModel | None:
        backend = resolve_openai_backend(core, provider)
        return OpenAIEmbeddingModel(backend, model) if backend is not None else None

    registrar.register_embedding("openai", _create)
