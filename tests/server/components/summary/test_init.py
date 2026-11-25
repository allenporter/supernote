"""Unit tests for `supernote.server.components.summary.SummaryComponent`."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.components.conversion import ConversionComponent
from supernote.server.components.processor import ProcessorComponent
from supernote.server.components.summary import (
    SUMMARY_SERVICE_KEY,
    SummaryComponent,
    SummaryService,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_summary_component_full_lifecycle(
    component_core: ServerCore,
) -> None:
    """Verify SummaryComponent exposes SummaryService and runs setup -> start -> stop idempotently."""
    component = SummaryComponent()
    assert isinstance(component, Component)
    assert component.domain == "summary"
    assert component.dependencies == ("conversion",)
    assert component.platforms == ("http", "processor")

    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(ProcessorComponent())
    loader.register(ConversionComponent())
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    service = component_core.app[SUMMARY_SERVICE_KEY]
    assert isinstance(service, SummaryService)
    assert service._purge_task is None

    await loader.async_start_all(component_core)
    assert service._purge_task is not None
    assert not service._purge_task.done()

    await loader.async_stop_all(component_core)
    assert service._purge_task is None
    await loader.async_stop_all(component_core)


async def test_summary_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(ProcessorComponent())
    loader.register(ConversionComponent())
    loader.register(SummaryComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
