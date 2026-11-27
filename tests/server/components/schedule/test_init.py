"""Unit tests for `supernote.server.components.schedule.ScheduleComponent`."""

from __future__ import annotations

from supernote.server.components.schedule import (
    SCHEDULE_SERVICE_KEY,
    ScheduleService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_schedule_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("schedule")
    component = loader.get("schedule")
    assert isinstance(component, Component)
    assert component.domain == "schedule"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")
    assert isinstance(component_core.app[SCHEDULE_SERVICE_KEY], ScheduleService)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_schedule_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("schedule", start=False)
    await loader.async_stop_all(component_core)
