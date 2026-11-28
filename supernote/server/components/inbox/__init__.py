"""Read-it-later and e-ink document publishing component (`InboxComponent`).

Converts Markdown notes and research briefs into e-ink-friendly `.epub` and
`.pdf` documents ready to drop into `/INBOX` for automatic sync to connected
Supernote devices.

This component owns the pure-Python document builder (`builder.py`) and will
host the `http` and `mcp` delivery surfaces (`POST /api/extended/inbox/send`
and `send_to_inbox`) independently of low-level VFS file tools (`files`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

__all__ = ["InboxComponent"]


class InboxComponent:
    """Vertical component for converting and delivering reading material to `/INBOX`."""

    domain = "inbox"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """No-op setup; platform surfaces are wired in follow-up slices."""

    async def async_start(self, core: ServerCore) -> None:
        """No-op start."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op stop."""
