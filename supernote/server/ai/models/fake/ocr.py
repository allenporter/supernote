"""Fake OCR model for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.ocr import OcrModel

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "FakeOcrModel",
    "create_ocr_model",
]


class FakeOcrModel(OcrModel):
    """Fake OCR model returning deterministic page transcripts."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    @property
    def model_id(self) -> str:
        return "fake-ocr-v1"

    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        self.calls.append((png_data, prompt))
        return f"Transcribed ({len(png_data)} bytes)"


def create_ocr_model(_config: ServerConfig) -> OcrModel:
    """Create a `FakeOcrModel`."""
    return FakeOcrModel()
