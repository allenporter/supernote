"""Unit tests for `supernote.server.components.events.EventsComponent`."""

from __future__ import annotations

from supernote.server.components.events import (
    EVENT_LOG_SERVICE_KEY,
    EventLogService,
    EventsComponent,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_events_component_lifecycle(component_core: ServerCore) -> None:
    """Verify EventsComponent registers EventLogService and supports idempotent lifecycle."""
    component = EventsComponent()
    assert isinstance(component, Component)
    assert component.domain == "events"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    service = component_core.app[EVENT_LOG_SERVICE_KEY]
    assert isinstance(service, EventLogService)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    # Idempotent second stop
    await loader.async_stop_all(component_core)


async def test_events_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(EventsComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
