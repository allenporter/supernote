"""Fake OCR model for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.ocr import OcrModel

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = [
    "FakeOcrModel",
    "async_setup_ocr",
    "create_ocr_model",
]


class FakeOcrModel(OcrModel):
    """Fake OCR model returning deterministic page transcripts."""

    def __init__(
        self,
        model_id: str = "fake-ocr-v1",
        provider: str = "fake",
    ) -> None:
        self._model_id = model_id
        self._provider = provider
        self.calls: list[tuple[bytes, str]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        self.calls.append((png_data, prompt))
        return f"Transcribed ({len(png_data)} bytes)"


def create_ocr_model(config: ServerConfig) -> OcrModel | None:
    """Create a `FakeOcrModel` from `ServerConfig`, or `None` if unconfigured."""
    if config.ai.ocr is None:
        return None
    return FakeOcrModel(
        model_id=config.ai.ocr.model,
        provider=config.ai.ocr.provider,
    )


async def async_setup_ocr(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``fake`` OCR provider with `AiRegistrar`."""
    registrar.register_ocr("fake", create_ocr_model)
