"""Google Gemini AI provider component (`GeminiComponent`).

Provides OCR, notebook summarization, and semantic embedding models backed by
the Google Gemini API, registering provider type ``"gemini"`` onto the ``ocr``,
``summary``, and ``embedding`` platforms hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .config import GeminiConfig

__all__ = ["GeminiComponent"]


class GeminiComponent:
    """AI provider component registering Gemini OCR, summary, and embedding models."""

    domain = "gemini"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr", "summary", "embedding", "text")

    def __init__(self) -> None:
        self._config: GeminiConfig = GeminiConfig()

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Parse `GeminiConfig` for Gemini model registration."""
        self._config = GeminiConfig.from_dict(dict(config))

    async def async_start(self, core: ServerCore) -> None:
        """No-op; Gemini clients run on demand with no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; Gemini clients require no teardown."""
