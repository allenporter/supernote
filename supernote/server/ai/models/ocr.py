"""Page transcription (OCR) model interface and concurrency wrapper.

OCR models convert rasterized PNG images of handwritten or printed notebook
pages into plain-text transcripts. Callers build the transcription prompt
(including page metadata and custom notebook instructions) via
`format_ocr_prompt` and pass both the image bytes and prompt to
`OcrModel.extract_text`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "ConcurrencyLimitedOcrModel",
    "OcrModel",
    "create_ocr_model",
]


class OcrModel(ABC):
    """Abstract interface for a page-transcription (OCR) model."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying OCR model (used for task tracking and logs)."""

    @abstractmethod
    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        """Extract handwritten or printed text from a rasterized PNG page image."""


class ConcurrencyLimitedOcrModel(OcrModel):
    """Wraps an `OcrModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: OcrModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        async with self._semaphore:
            return await self._model.extract_text(png_data, prompt)


def create_ocr_model(config: ServerConfig) -> OcrModel | None:
    """Create the configured `OcrModel` wrapped with concurrency limiting."""
    if not config.gemini_api_key or not config.gemini_api_key.strip():
        return None

    from supernote.server.ai.models.gemini.ocr import (  # noqa: PLC0415
        create_ocr_model as create_gemini_ocr_model,
    )

    model = create_gemini_ocr_model(config)
    if model is None:
        return None
    # TODO(#301): Generalize `gemini_max_concurrency` across AI providers.
    return ConcurrencyLimitedOcrModel(
        model, max_concurrency=config.gemini_max_concurrency
    )
