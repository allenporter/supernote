"""Unit tests for `supernote.server.components.integrity.IntegrityComponent`."""

from __future__ import annotations

from supernote.server.components.integrity import (
    INTEGRITY_SERVICE_KEY,
    IntegrityComponent,
    IntegrityService,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_integrity_component_lifecycle(component_core: ServerCore) -> None:
    """Verify IntegrityComponent exposes IntegrityService and supports idempotent lifecycle."""
    component = IntegrityComponent()
    assert isinstance(component, Component)
    assert component.domain == "integrity"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[INTEGRITY_SERVICE_KEY], IntegrityService)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_integrity_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(IntegrityComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
