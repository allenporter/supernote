"""Notebook structural metadata vertical component (`NoteMetadataComponent`).

Owns the read surface for device-authored `.note` structure—notebook headers,
per-page metadata (styles, stars, keywords, blank flags), outgoing links,
native titles, and signed title handwriting crop previews (`GET /api/oss/title/*`).

Provides `NoteMetadataComponent`, `NoteMetadataService`, and
`NOTE_METADATA_SERVICE_KEY` (for sibling components declaring
``dependencies = ("note_metadata",)``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .service import NOTE_METADATA_SERVICE_KEY, NoteMetadataService

__all__ = [
    "NOTE_METADATA_SERVICE_KEY",
    "NoteMetadataComponent",
    "NoteMetadataService",
]


class NoteMetadataComponent:
    """Vertical component serving structured `.note` metadata and title crop previews."""

    domain = "note_metadata"
    dependencies: tuple[str, ...] = ("processor",)
    platforms: tuple[str, ...] = ("http", "processor")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `NoteMetadataService` and expose it via `NOTE_METADATA_SERVICE_KEY`."""
        _ = config
        core.app[NOTE_METADATA_SERVICE_KEY] = NoteMetadataService(
            session_manager=core.session_manager,
            blob_storage=core.blob_storage,
        )

    async def async_start(self, core: ServerCore) -> None:
        """No-op; metadata reads and title crop renders run on demand."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; note metadata service holds no background tasks."""
