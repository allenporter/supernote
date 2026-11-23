"""Unit tests for `supernote.server.components.metrics.MetricsComponent`."""

from __future__ import annotations

from supernote.server.components.metrics import (
    STORAGE_METRICS_COLLECTOR_KEY,
    MetricsComponent,
    StorageMetricsCollector,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_metrics_component_lifecycle(component_core: ServerCore) -> None:
    component = MetricsComponent()
    assert isinstance(component, Component)
    assert component.domain == "metrics"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(
        component_core.app[STORAGE_METRICS_COLLECTOR_KEY], StorageMetricsCollector
    )

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_metrics_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(MetricsComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
