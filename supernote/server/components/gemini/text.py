"""Gemini-backed structured JSON text generation model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from google.genai import types

from supernote.server.ai.models.text import TextGenerationModel, parse_json_object
from supernote.server.metrics import AIStage

from . import resolve_gemini_backend
from .backend import GeminiBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiTextGenerationModel",
    "async_setup_text",
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


async def async_setup_text(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` text generation provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> TextGenerationModel | None:
        backend = resolve_gemini_backend(core, provider)
        return (
            GeminiTextGenerationModel(backend, model) if backend is not None else None
        )

    registrar.register_text("gemini", _create)
