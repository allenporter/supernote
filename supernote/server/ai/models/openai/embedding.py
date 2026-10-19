"""OpenAI-compatible text embedding model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType

from .backend import OpenAIBackend, create_openai_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "OpenAIEmbeddingModel",
    "create_embedding_model",
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
    def model_id(self) -> str:
        return self._model_name

    async def _embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        return await self._backend.embeddings(model=self._model_name, text=text)


def create_embedding_model(config: ServerConfig) -> EmbeddingModel | None:
    """Create an `OpenAIEmbeddingModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.embedding
    backend = create_openai_backend(config.ai.providers)
    if model_cfg is None or backend is None:
        return None
    return OpenAIEmbeddingModel(backend, model_cfg.model)
