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

from .backend import GeminiBackend, create_gemini_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "GeminiEmbeddingModel",
    "create_embedding_model",
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


def create_embedding_model(config: ServerConfig) -> EmbeddingModel | None:
    """Create a `GeminiEmbeddingModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.embedding
    if model_cfg is None:
        return None
    backend = create_gemini_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return GeminiEmbeddingModel(backend, model_cfg.model)
