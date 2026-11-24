"""Gemini-backed structured JSON text generation model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from google.genai import types

from supernote.server.ai.models.text import TextGenerationModel, parse_json_object
from supernote.server.metrics import AIStage

from .backend import GeminiBackend, create_gemini_backend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiTextGenerationModel",
    "async_setup_text",
    "create_text_model",
]


class GeminiTextGenerationModel(TextGenerationModel):
    """Gemini-backed structured JSON text generation model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
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
        _ = (schema_name, stage)
        response = await self._backend.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=dict(response_schema),
            ),
        )
        return parse_json_object(response.text)


def create_text_model(config: ServerConfig) -> TextGenerationModel | None:
    """Create a `GeminiTextGenerationModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.text
    if model_cfg is None:
        return None
    backend = create_gemini_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return GeminiTextGenerationModel(backend, model_cfg.model)


async def async_setup_text(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` text generation provider with `AiRegistrar`."""
    registrar.register_text("gemini", create_text_model)
