"""Deterministic in-memory AI model component (`FakeAiComponent`).

Provides fake OCR, summary, and embedding models for testing and local
verification, registering provider type ``"fake"`` onto the ``ocr``,
``summary``, and ``embedding`` platforms hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["FakeAiComponent"]


class FakeAiComponent:
    """AI provider component registering the built-in ``fake`` OCR, summary, and embedding models."""

    domain = "fake_ai"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr", "summary", "embedding")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op; fake model factories register via the `ocr`, `summary`, and `embedding` platforms."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op; fake models hold no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; fake models require no teardown."""
