"""Web UI static SPA server component (`WebUiComponent`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["WebUiComponent"]


class WebUiComponent:
    """Vertical component serving the static Vue 3 Web UI via the `http` platform."""

    domain = "web_ui"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op; static routes and cache headers are mounted via `http.py`."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op; static assets are served directly by `aiohttp`."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; static routes require no teardown."""
