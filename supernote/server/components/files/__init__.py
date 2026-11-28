"""Virtual File System (VFS) MCP tools component (`FilesComponent`).

Exposes MCP tools (`list_files`, `prepare_upload`, `commit_upload`) backed by
core `FileService`, `UrlSigner`, `CoordinationService`, and `/api/oss/upload`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["FilesComponent"]


class FilesComponent:
    """Vertical component exposing VFS browsing and staged upload tools over MCP."""

    domain = "files"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("mcp",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op setup; tools delegate directly to core services."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op start."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op stop."""
