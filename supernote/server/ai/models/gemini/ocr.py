"""Gemini-backed page OCR model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.models.ocr import OcrModel

from .backend import GeminiBackend

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
    api_key = config.gemini_api_key
    if not api_key or not api_key.strip():
        return None
    return GeminiOcrModel(GeminiBackend(api_key), config.gemini_ocr_model)
