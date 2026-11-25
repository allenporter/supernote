"""Unit tests for `supernote.server.components.events.EventsComponent`."""

from __future__ import annotations

from supernote.server.components.events import (
    EVENT_LOG_SERVICE_KEY,
    EventLogService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_events_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify EventsComponent registers EventLogService and supports idempotent lifecycle."""
    loader = await load_components("events")
    component = loader.get("events")
    assert isinstance(component, Component)
    assert component.domain == "events"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")
    assert isinstance(component_core.app[EVENT_LOG_SERVICE_KEY], EventLogService)

    await loader.async_stop_all(component_core)
    # Idempotent second stop
    await loader.async_stop_all(component_core)


async def test_events_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("events", start=False)
    await loader.async_stop_all(component_core)
