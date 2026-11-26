"""Gemini-backed page OCR model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.models.ocr import OcrModel

from . import resolve_gemini_backend
from .backend import GeminiBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiOcrModel",
    "async_setup_ocr",
]


class GeminiOcrModel(OcrModel):
    """Gemini-backed page OCR model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return self._backend.provider

    @property
    def model_id(self) -> str:
        return self._model_name

    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        parts = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=png_data, mime_type="image/png"),
        ]
        response = await self._backend.generate_content(
            model=self._model_name,
            contents=[types.Content(parts=parts)],
            config=types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH
            ),
        )
        return response.text if response.text else ""


async def async_setup_ocr(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` OCR provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> OcrModel | None:
        backend = resolve_gemini_backend(core, provider)
        return GeminiOcrModel(backend, model) if backend is not None else None

    registrar.register_ocr("gemini", _create)
