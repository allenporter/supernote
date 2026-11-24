"""LLM Wiki server component (`WikiComponent`).

Owns per-user wiki storage (`WikiService`) and Obsidian Markdown/ZIP export
(`WikiExportService`). Registered opt-in (`default_enabled=False`) in
`BUILTIN_COMPONENTS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .config import WikiConfig
from .export import WIKI_EXPORT_SERVICE_KEY, WikiExportService
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = [
    "WIKI_EXPORT_SERVICE_KEY",
    "WIKI_SERVICE_KEY",
    "WikiComponent",
    "WikiConfig",
    "WikiExportService",
    "WikiService",
]


class WikiComponent:
    """Vertical component managing per-user LLM wiki storage and export."""

    domain = "wiki"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._config: WikiConfig | None = None

    @property
    def config(self) -> WikiConfig | None:
        """Validated `WikiConfig` after `async_setup`."""
        return self._config

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate `WikiConfig`, instantiate services, and expose app keys."""
        self._config = WikiConfig.from_dict(config)
        service = WikiService(core.session_manager)
        core.app[WIKI_SERVICE_KEY] = service
        core.app[WIKI_EXPORT_SERVICE_KEY] = WikiExportService(service)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; background compilation worker attaches in PR 4."""

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently release component state."""
        self._config = None
