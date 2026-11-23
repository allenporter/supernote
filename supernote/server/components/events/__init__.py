"""Domain event log vertical server component (`EventsComponent`).

Persists per-user domain events (`UserEventDO` in `f_user_event`), serves the
incremental cursor-paginated feed over HTTP (`GET /api/extended/events`), and
runs periodic retention pruning.

### Core vs. Component Boundary

- **Core (`supernote.server.events`)**: Owns the in-process `LocalEventBus`
  and the `Event` / `DomainEvent` / `DomainEventRecorded` dataclasses exposed
  on `ServerCore.event_bus`. Core services (`FileService`, `ProcessorService`,
  `SummaryService`) and sibling components (`schedule`, `socketio`, `webhooks`)
  publish and subscribe on `core.event_bus` without importing this component.
- **Component (`supernote.server.components.events`)**: Owns durable event log
  persistence (`EventLogService`), cursor codec & feed models (`models.py`),
  periodic retention pruning (`async_start` / `async_stop`), and the HTTP feed
  endpoint (`http.py`).

### Internal Python API for Sibling Components & Plugins

Components that need to query or append to the durable event log (for example,
an MCP `list_events` tool or an activity feed plugin) should declare
``dependencies = ("events",)`` and access the typed service key:

```python
from supernote.server.components.events import EVENT_LOG_SERVICE_KEY

event_log = core.app[EVENT_LOG_SERVICE_KEY]
page = await event_log.list_events(
    user_id=user_id,
    sync_token=cursor,
    event_types=["note.*", "schedule.*"],
)
```

### Lifecycle

1. `async_setup`: Instantiates `EventLogService` bound to `core.session_manager`,
   `core.coordination`, `core.event_bus`, and `core.config.event_log_retention_days`,
   and stores it on `core.app[EVENT_LOG_SERVICE_KEY]`.
2. `async_start`: Starts the background retention-pruning loop (no-op when
   `event_log_retention_days == 0`).
3. `async_stop`: Idempotently stops the retention-pruning loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .models import EventFeedPage
from .service import EVENT_LOG_SERVICE_KEY, EventLogService

__all__ = [
    "EVENT_LOG_SERVICE_KEY",
    "EventFeedPage",
    "EventLogService",
    "EventsComponent",
]


class EventsComponent:
    """Vertical component managing durable domain event log persistence, pruning, and HTTP feed."""

    domain = "events"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http", "mcp")

    def __init__(self) -> None:
        self._service: EventLogService | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `EventLogService` and expose it via `EVENT_LOG_SERVICE_KEY`."""
        service = EventLogService(
            session_manager=core.session_manager,
            coordination_service=core.coordination,
            event_bus=core.event_bus,
            retention_days=core.config.event_log_retention_days,
        )
        core.app[EVENT_LOG_SERVICE_KEY] = service
        self._service = service

    async def async_start(self, core: ServerCore) -> None:
        """Start periodic retention pruning of expired domain events."""
        assert self._service is not None
        await self._service.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop the background retention-pruning task."""
        service = self._service
        self._service = None
        if service is not None:
            await service.stop()
