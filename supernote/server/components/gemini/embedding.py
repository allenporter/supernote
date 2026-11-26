"""Gemini-backed text embedding model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    EmbeddingModel,
    EmbeddingTaskType,
    validate_embedding_vector,
)

from . import resolve_gemini_backend
from .backend import GeminiBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiEmbeddingModel",
    "async_setup_embedding",
]


class GeminiEmbeddingModel(EmbeddingModel):
    """Gemini-backed text embedding model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
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
        response = await self._backend.embed_content(
            model=self._model_name,
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type.value),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise AIError("No embeddings returned from Gemini API")
        return validate_embedding_vector(
            response.embeddings[0].values, self._model_name
        )


async def async_setup_embedding(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` embedding provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> EmbeddingModel | None:
        backend = resolve_gemini_backend(core, provider)
        return GeminiEmbeddingModel(backend, model) if backend is not None else None

    registrar.register_embedding("gemini", _create)
