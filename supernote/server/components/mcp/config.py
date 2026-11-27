"""Configuration model for the Model Context Protocol (MCP) server component (`McpConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["McpConfig"]


@dataclass
class McpConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.mcp`."""

    enabled: bool = True
    """Whether the Streamable HTTP MCP resource server is enabled."""

    port: int = 8081
    """TCP port for the MCP server (`0` selects an ephemeral OS port in tests)."""

    base_url: str | None = None
    """Optional external base URL for RFC 9728 Protected Resource discovery behind a proxy."""

    def __post_init__(self) -> None:
        if isinstance(self.port, bool) or not (0 <= self.port <= 65535):
            raise ValueError("mcp.port must be an integer between 0 and 65535")

    def resolve_base_url(self, host: str) -> str:
        """Return the effective MCP resource server base URL without a trailing slash."""
        if self.base_url:
            return self.base_url.rstrip("/")
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        return f"http://{display_host}:{self.port}"
