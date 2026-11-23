"""Unit tests for `supernote.server.components.schedule.ScheduleComponent`."""

from __future__ import annotations

from supernote.server.components.schedule import (
    SCHEDULE_SERVICE_KEY,
    ScheduleComponent,
    ScheduleService,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_schedule_component_lifecycle(component_core: ServerCore) -> None:
    component = ScheduleComponent()
    assert isinstance(component, Component)
    assert component.domain == "schedule"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[SCHEDULE_SERVICE_KEY], ScheduleService)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_schedule_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(ScheduleComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
