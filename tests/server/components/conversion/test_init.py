"""Unit tests for `supernote.server.components.conversion.ConversionComponent`."""

from __future__ import annotations

from supernote.server.components.conversion import (
    CONVERSION_SERVICE_KEY,
    ConversionService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_conversion_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify ConversionComponent registers ConversionService and supports idempotent lifecycle."""
    loader = await load_components(
        "conversion",
        configs={"conversion": {"notebook_preview": False}},
    )
    component = loader.get("conversion")
    assert isinstance(component, Component)
    assert component.domain == "conversion"
    assert component.dependencies == ("ai", "processor")
    assert component.platforms == ("http", "processor")
    service = component_core.app[CONVERSION_SERVICE_KEY]
    assert isinstance(service, ConversionService)
    assert service.notebook_preview is False

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_conversion_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("conversion", start=False)
    await loader.async_stop_all(component_core)
