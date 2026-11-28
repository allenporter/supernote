"""Cross-notebook page timeline vertical component (`TimelineComponent`).

Aggregates device-authored page creation timestamps (`NotePageMetadataDO.page_created_at`)
and synced page edit deltas (`note.pages_delta` in `UserEventDO`) into a paginated
day-grouped feed (`GET /api/extended/timeline/pages`) and calendar day-count index
(`GET /api/extended/timeline/days`).

Provides `TimelineComponent`, `TimelineService`, and `TIMELINE_SERVICE_KEY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .service import TIMELINE_SERVICE_KEY, TimelineService

__all__ = [
    "TIMELINE_SERVICE_KEY",
    "TimelineComponent",
    "TimelineService",
]


class TimelineComponent:
    """Vertical component serving the cross-notebook page activity timeline."""

    domain = "timeline"
    dependencies: tuple[str, ...] = ("note_metadata", "events")
    platforms: tuple[str, ...] = ("http",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `TimelineService` and expose it via `TIMELINE_SERVICE_KEY`."""
        _ = config
        core.app[TIMELINE_SERVICE_KEY] = TimelineService(
            session_manager=core.session_manager,
        )

    async def async_start(self, core: ServerCore) -> None:
        """No-op; timeline queries run on demand."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; timeline service holds no background tasks."""
