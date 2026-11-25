"""Web UI static SPA server component (`WebUiComponent`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .config import WebUiConfig

__all__ = ["WEB_UI_CONFIG_KEY", "WebUiComponent", "WebUiConfig"]

WEB_UI_CONFIG_KEY: web.AppKey[WebUiConfig] = web.AppKey("web_ui_config")


class WebUiComponent:
    """Vertical component serving the static Vue 3 Web UI via the `http` platform."""

    domain = "web_ui"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Parse `WebUiConfig` and register it on `core.app`."""
        core.app[WEB_UI_CONFIG_KEY] = WebUiConfig.from_dict(dict(config))

    async def async_start(self, core: ServerCore) -> None:
        """No-op; static assets are served directly by `aiohttp`."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; static routes require no teardown."""
