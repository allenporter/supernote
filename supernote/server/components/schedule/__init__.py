"""Schedule task management server component (`ScheduleComponent`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .service import SCHEDULE_SERVICE_KEY, ScheduleService

__all__ = [
    "SCHEDULE_SERVICE_KEY",
    "ScheduleComponent",
    "ScheduleService",
]


class ScheduleComponent:
    """Vertical component managing schedule task groups, tasks, and HTTP routes."""

    domain = "schedule"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http", "mcp")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `ScheduleService` and expose it via `SCHEDULE_SERVICE_KEY`."""
        core.app[SCHEDULE_SERVICE_KEY] = ScheduleService(
            core.session_manager, core.event_bus
        )

    async def async_start(self, core: ServerCore) -> None:
        """No-op; schedule operations are driven by HTTP requests and events."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; schedule service holds no background tasks."""
