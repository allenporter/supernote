"""Google Gemini AI provider component (`GeminiComponent`).

Provides OCR, notebook summarization, and semantic embedding models backed by
the Google Gemini API, registering provider type ``"gemini"`` onto the ``ocr``,
``summary``, and ``embedding`` platforms hosted by `supernote.server.components.ai`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp

from supernote.server.core import ServerCore
from supernote.server.keys import COMPONENT_LOADER_KEY

from .backend import GeminiBackend, create_gemini_backend
from .config import GeminiConfig

__all__ = ["GeminiComponent", "resolve_gemini_backend"]

logger = logging.getLogger(__name__)


class GeminiComponent:
    """AI provider component registering Gemini OCR, summary, embedding, and text models."""

    domain = "gemini"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("ocr", "summary", "embedding", "text")

    def __init__(self) -> None:
        self._config: GeminiConfig = GeminiConfig()
        self._session: aiohttp.ClientSession | None = None
        self._backends: dict[str, GeminiBackend] = {}

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Shared `aiohttp.ClientSession` owned by this component, if set up."""
        return self._session

    def get_backend(self, provider: str) -> GeminiBackend | None:
        """Return a shared `GeminiBackend` for ``provider`` backed by this component's session."""
        if provider in self._backends:
            return self._backends[provider]
        backend = create_gemini_backend(
            self._config.providers, provider, session=self._session
        )
        if backend is not None:
            self._backends[provider] = backend
        return backend

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Parse `GeminiConfig` and create the shared `aiohttp.ClientSession`."""
        await self.async_stop(core)
        self._config = GeminiConfig.from_dict(dict(config))
        self._session = aiohttp.ClientSession()

    async def async_start(self, core: ServerCore) -> None:
        """No-op; Gemini clients run on demand with no background tasks."""

    async def async_stop(self, core: ServerCore) -> None:
        """Close all shared `GeminiBackend` clients and the component `ClientSession` idempotently."""
        backends = list(self._backends.values())
        self._backends.clear()
        for backend in backends:
            try:
                await backend.close()
            except Exception:
                logger.exception("Error closing Gemini backend %r", backend.provider)
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()


def resolve_gemini_backend(core: ServerCore, provider: str) -> GeminiBackend | None:
    """Resolve a `GeminiBackend` for ``provider`` from the loaded `GeminiComponent`."""
    comp = core.app[COMPONENT_LOADER_KEY].get("gemini")
    assert isinstance(comp, GeminiComponent)
    return comp.get_backend(provider)
