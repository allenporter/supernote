"""OAuth 2.1 / IndieAuth Authorization Server component (`OAuthComponent`).

Encapsulates the OAuth 2.1 provider, token models, and ASGI HTTP endpoints
(`/authorize`, `/token`, `/revoke`, `/login-bridge`, `/.well-known/oauth-authorization-server`)
behind a standalone vertical component so REST and MCP consumers depend on `oauth`
rather than coupling directly to the underlying OAuth library.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["OAuthComponent"]


class OAuthComponent:
    """Vertical component providing OAuth 2.1 authorization endpoints via the `http` platform."""

    domain = "oauth"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op; OAuth 2.1 endpoints mount via the `http` platform (`oauth/http.py`)."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op; OAuth endpoints are served directly on the primary `aiohttp` app."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; OAuth endpoints require no background task teardown."""
