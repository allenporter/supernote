"""OpenAI-compatible AI provider component (`OpenAIComponent`).

Provides OCR, notebook summarization, and semantic embedding models backed by
OpenAI-compatible APIs (OpenAI, Ollama, vLLM, llama.cpp), registering provider
type ``"openai"`` onto the ``ocr``, ``summary``, and ``embedding`` platforms
hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["OpenAIComponent"]


class OpenAIComponent:
    """AI provider component registering OpenAI-compatible OCR, summary, and embedding models."""

    domain = "openai"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr", "summary", "embedding")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op; OpenAI factories register via the `ocr`, `summary`, and `embedding` platforms."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op; OpenAI clients run on demand with no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; OpenAI clients require no teardown."""
