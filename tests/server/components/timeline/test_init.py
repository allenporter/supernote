"""Unit tests for `supernote.server.components.timeline.TimelineComponent`."""

from __future__ import annotations

from supernote.server.components.timeline import TIMELINE_SERVICE_KEY, TimelineService
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_timeline_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify TimelineComponent registers TimelineService and supports idempotent lifecycle."""
    loader = await load_components("timeline")
    component = loader.get("timeline")
    assert isinstance(component, Component)
    assert component.domain == "timeline"
    assert component.dependencies == ("note_metadata", "events")
    assert component.platforms == ("http",)
    assert isinstance(component_core.app[TIMELINE_SERVICE_KEY], TimelineService)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_timeline_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("timeline", start=False)
    await loader.async_stop_all(component_core)
