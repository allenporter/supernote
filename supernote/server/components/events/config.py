"""Configuration model for the domain event log component (`EventsConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["EventsConfig"]


@dataclass
class EventsConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.events`."""

    enabled: bool = True
    """Whether durable domain event log persistence and HTTP/MCP feeds are enabled."""

    retention_days: int = 90
    """Number of days to retain domain events in `f_user_event` (`0` = retain indefinitely).

    Defaults to 90 days so intermittent sync clients (such as weekly/monthly wiki
    compilation or cursor-based event consumers) can catch up from their last
    sync token while bounding SQLite table growth on long-running servers.
    """

    def __post_init__(self) -> None:
        if isinstance(self.retention_days, bool) or self.retention_days < 0:
            raise ValueError("events.retention_days must be >= 0")
