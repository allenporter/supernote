"""Page transcription (OCR) model interface, telemetry, and concurrency wrappers.

OCR models convert rasterized PNG images of handwritten or printed notebook
pages into plain-text transcripts. Callers build the transcription prompt
(including page metadata and custom notebook instructions) via
`format_ocr_prompt` and pass both the image bytes and prompt to
`OcrModel.extract_text`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from supernote.server.metrics import AIStage, init_ai_metrics, track_ai_request

__all__ = [
    "ConcurrencyLimitedOcrModel",
    "InstrumentedOcrModel",
    "OcrModel",
    "PromptOverrideOcrModel",
]


class OcrModel(ABC):
    """Abstract interface for a page-transcription (OCR) model."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Identifier of the configured AI provider serving this model."""

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


class InstrumentedOcrModel(OcrModel):
    """Wraps an `OcrModel` to record Prometheus request and latency metrics."""

    def __init__(self, model: OcrModel) -> None:
        self._model = model
        init_ai_metrics(
            provider=model.provider,
            model=model.model_id,
            stage=AIStage.OCR,
        )

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        with track_ai_request(
            provider=self.provider,
            model=self.model_id,
            stage=AIStage.OCR,
        ):
            return await self._model.extract_text(png_data, prompt)


class ConcurrencyLimitedOcrModel(OcrModel):
    """Wraps an `OcrModel` to bound maximum concurrent in-flight requests."""

    def __init__(self, model: OcrModel, max_concurrency: int = 5) -> None:
        self._model = model
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        async with self._semaphore:
            return await self._model.extract_text(png_data, prompt)


class PromptOverrideOcrModel(OcrModel):
    """Wraps an `OcrModel` to replace the caller's prompt with a fixed instruction."""

    def __init__(self, model: OcrModel, prompt: str) -> None:
        self._model = model
        self._prompt = prompt

    @property
    def provider(self) -> str:
        return self._model.provider

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        return await self._model.extract_text(png_data, self._prompt)
