"""OpenAI-compatible structured JSON text generation model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from supernote.server.ai.models.text import TextGenerationModel, parse_json_object
from supernote.server.metrics import AIStage

from .backend import OpenAIBackend, create_openai_backend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = [
    "OpenAITextGenerationModel",
    "async_setup_text",
    "create_text_model",
]


class OpenAITextGenerationModel(TextGenerationModel):
    """OpenAI-compatible structured JSON text generation model."""

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return self._backend.provider

    @property
    def model_id(self) -> str:
        return self._model_name

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        _ = stage
        text = await self._backend.chat_completion(
            model=self._model_name,
            content=[{"type": "text", "text": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": dict(response_schema),
                },
            },
        )
        return parse_json_object(text)


def create_text_model(config: ServerConfig) -> TextGenerationModel | None:
    """Create an `OpenAITextGenerationModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.text
    if model_cfg is None:
        return None
    backend = create_openai_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return OpenAITextGenerationModel(backend, model_cfg.model)


async def async_setup_text(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``openai`` text generation provider with `AiRegistrar`."""
    registrar.register_text("openai", create_text_model)
