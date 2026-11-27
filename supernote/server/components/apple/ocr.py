"""Apple Vision page OCR model (`AppleOcrModel`).

This module implements `supernote.server.ai.models.ocr.OcrModel` using macOS `VNRecognizeTextRequest`
via `supernote.server.components.apple.backend.AppleVisionBackend`, supporting `accurate` and `fast`
recognition levels (`RecognitionLevel`) for local on-device `.note` page transcription.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.ocr import OcrModel

from .backend import AppleVisionBackend, RecognitionLevel, create_apple_backend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "SUPPORTED_APPLE_OCR_MODELS",
    "AppleOcrModel",
    "async_setup_ocr",
]

SUPPORTED_APPLE_OCR_MODELS: tuple[str, ...] = tuple(
    level.value for level in RecognitionLevel
)


def _resolve_recognition_level(model_name: str) -> RecognitionLevel:
    """Validate a canonical Apple OCR `model` identifier."""
    try:
        return RecognitionLevel(model_name)
    except ValueError as err:
        supported = ", ".join(SUPPORTED_APPLE_OCR_MODELS)
        raise ValueError(
            f"Unsupported Apple OCR model {model_name!r}; expected one of: {supported}"
        ) from err


class AppleOcrModel(OcrModel):
    """On-device macOS Vision OCR model (`VNRecognizeTextRequest`).

    Vision is an optical text recognizer rather than a promptable VLM, so
    `prompt` is accepted to satisfy `OcrModel` but is not sent to the model.
    """

    def __init__(self, backend: AppleVisionBackend, model_name: str) -> None:
        self._level = _resolve_recognition_level(model_name)
        self._backend = backend

    @property
    def provider(self) -> str:
        return self._backend.provider

    @property
    def model_id(self) -> str:
        return self._level.value

    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        return await self._backend.recognize_text(png_data, level=self._level)


async def async_setup_ocr(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``apple`` OCR provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> OcrModel:
        _resolve_recognition_level(model)
        backend = create_apple_backend(provider)
        return AppleOcrModel(backend, model)

    registrar.register_ocr("apple", _create)
