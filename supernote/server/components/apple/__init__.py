"""Apple Vision on-device OCR component (`AppleComponent`).

Provides zero-cost, on-device handwriting OCR on macOS via Apple's Vision
framework (`VNRecognizeTextRequest`), registering provider type ``"apple"``
onto the ``ocr`` platform hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["AppleComponent"]


class AppleComponent:
    """AI provider component registering the macOS Apple Vision OCR backend."""

    domain = "apple"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op; the Apple Vision OCR factory registers via the `ocr` platform."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op; Apple Vision runs on demand with no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; Apple Vision requires no teardown."""
