"""OAuth 2.1 Authorization Server component (`OAuthComponent`).

Implements OAuth 2.1 authorization for MCP and third-party clients on the
primary HTTP server, including client metadata discovery, interactive login and
consent bridging, and token issuance/revocation. By encapsulating the
Starlette/MCP OAuth provider behind a vertical component, the rest of the server
stays decoupled from the underlying OAuth library while `mcp` declares a clean
dependency on `oauth`.

Provides `OAuthComponent`.
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
