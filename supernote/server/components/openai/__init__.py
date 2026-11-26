"""OpenAI-compatible AI provider component (`OpenAIComponent`).

Provides OCR, notebook summarization, and semantic embedding models backed by
OpenAI-compatible APIs (OpenAI, Ollama, vLLM, llama.cpp), registering provider
type ``"openai"`` onto the ``ocr``, ``summary``, and ``embedding`` platforms
hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp

from supernote.server.core import ServerCore
from supernote.server.keys import COMPONENT_LOADER_KEY

from .backend import REQUEST_TIMEOUT, OpenAIBackend, create_openai_backend
from .config import OpenAIConfig

__all__ = ["OpenAIComponent", "resolve_openai_backend"]


class OpenAIComponent:
    """AI provider component registering OpenAI-compatible OCR, summary, embedding, and text models."""

    domain = "openai"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr", "summary", "embedding", "text")

    def __init__(self) -> None:
        self._config: OpenAIConfig = OpenAIConfig()
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Shared `aiohttp.ClientSession` owned by this component, if set up."""
        return self._session

    def get_backend(self, provider: str) -> OpenAIBackend | None:
        """Create an `OpenAIBackend` for ``provider`` backed by this component's session."""
        return create_openai_backend(
            self._config.providers, provider, session=self._session
        )

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Parse `OpenAIConfig` and create the shared `aiohttp.ClientSession`."""
        await self.async_stop(core)
        self._config = OpenAIConfig.from_dict(dict(config))
        self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; OpenAI clients run on demand with no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """Close the component's shared `aiohttp.ClientSession` idempotently."""
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()


def resolve_openai_backend(core: ServerCore, provider: str) -> OpenAIBackend | None:
    """Resolve an `OpenAIBackend` for ``provider`` from the loaded `OpenAIComponent`."""
    comp = core.app[COMPONENT_LOADER_KEY].get("openai")
    assert isinstance(comp, OpenAIComponent)
    return comp.get_backend(provider)
