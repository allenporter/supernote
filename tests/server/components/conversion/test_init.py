"""Unit tests for `supernote.server.components.conversion.ConversionComponent`."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.components.conversion import (
    CONVERSION_SERVICE_KEY,
    ConversionComponent,
    ConversionService,
)
from supernote.server.components.processor import ProcessorComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_conversion_component_lifecycle(component_core: ServerCore) -> None:
    """Verify ConversionComponent registers ConversionService and supports idempotent lifecycle."""
    component = ConversionComponent()
    assert isinstance(component, Component)
    assert component.domain == "conversion"
    assert component.dependencies == ("processor",)
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(ProcessorComponent())
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[CONVERSION_SERVICE_KEY], ConversionService)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_conversion_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(ProcessorComponent())
    loader.register(ConversionComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
