"""Cloud file management over MCP (`FilesComponent`).

Lets AI assistants browse a user's Supernote cloud folders (such as `/INBOX`
and `/DOCUMENT`) and upload reading material like Markdown, text, or PDFs so
they sync automatically to connected Supernote devices.

Core file storage and device sync live directly on `ServerCore.file_service`
(`FileService`), which always runs regardless of whether MCP is enabled. This
component is the thin MCP adapter layer that exposes those file operations as
MCP tools (`list_files`, `upload_document`, `create_folder`, and
`delete_item`), delegating to core `FileService` and `BlobStorage`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["FilesComponent"]


class FilesComponent:
    """Vertical component exposing VFS browsing and document upload tools over MCP."""

    domain = "files"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("mcp",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op setup; tools delegate directly to core services."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op start."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op stop."""
