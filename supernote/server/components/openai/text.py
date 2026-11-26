"""OpenAI-compatible structured JSON text generation model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from supernote.server.ai.models.text import TextGenerationModel, parse_json_object
from supernote.server.metrics import AIStage

from . import resolve_openai_backend
from .backend import OpenAIBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "OpenAITextGenerationModel",
    "async_setup_text",
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


async def async_setup_text(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``openai`` text generation provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> TextGenerationModel | None:
        backend = resolve_openai_backend(core, provider)
        return (
            OpenAITextGenerationModel(backend, model) if backend is not None else None
        )

    registrar.register_text("openai", _create)
