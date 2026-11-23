"""Apple Vision on-device OCR component (`AppleComponent`).

Provides zero-cost, on-device handwriting OCR on macOS via Apple's Vision
framework (`VNRecognizeTextRequest`), registering provider type ``"apple"``
onto the ``ocr`` platform hosted by `supernote.server.components.ai`.

**Model quality guidance** (from ``supernote-ocr-suite-v1``, see
``supernote.guides.ocr_benchmarks``):

- **`vision-accurate`** (21.7% mean CER / 9.8% median CER, 73.7% word F1,
  ~411 ms median latency): Solid as a fast, offline fallback for clean English
  prose search (3.0% CER, 93.0% word F1), but trails multimodal VLMs like
  ``gemini-3.5-flash-lite`` (2.3% mean CER, 99.0% word F1) on complex layouts
  (30.2% CER), multilingual pages (24.6% CER), and Bullet Journal structure
  (0% indentation/strikethrough fidelity).
- **`vision-fast`** (72.8% mean CER, 17.8% word F1): Not recommended for
  handwritten notes; Vision's fast path only reliably detects machine-printed
  text.
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
