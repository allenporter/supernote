"""Unit tests for `supernote.server.components.metrics.MetricsComponent`."""

from __future__ import annotations

from supernote.server.components.metrics import (
    STORAGE_METRICS_COLLECTOR_KEY,
    StorageMetricsCollector,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_metrics_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("metrics")
    component = loader.get("metrics")
    assert isinstance(component, Component)
    assert component.domain == "metrics"
    assert component.dependencies == ()
    assert component.platforms == ("http",)
    assert isinstance(
        component_core.app[STORAGE_METRICS_COLLECTOR_KEY], StorageMetricsCollector
    )

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_metrics_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("metrics", start=False)
    await loader.async_stop_all(component_core)
