"""Gemini-backed page OCR model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.models.ocr import OcrModel

from .backend import GeminiBackend, create_gemini_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "GeminiOcrModel",
    "create_ocr_model",
]


class GeminiOcrModel(OcrModel):
    """Gemini-backed page OCR model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

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


def create_ocr_model(config: ServerConfig) -> OcrModel | None:
    """Create a `GeminiOcrModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.ocr
    if model_cfg is None:
        return None
    backend = create_gemini_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return GeminiOcrModel(backend, model_cfg.model)
