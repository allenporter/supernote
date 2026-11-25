"""Unit tests for `supernote.server.components.integrity.IntegrityComponent`."""

from __future__ import annotations

from supernote.server.components.integrity import (
    INTEGRITY_SERVICE_KEY,
    IntegrityService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_integrity_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify IntegrityComponent exposes IntegrityService and supports idempotent lifecycle."""
    loader = await load_components("integrity")
    component = loader.get("integrity")
    assert isinstance(component, Component)
    assert component.domain == "integrity"
    assert component.dependencies == ()
    assert component.platforms == ("http",)
    assert isinstance(component_core.app[INTEGRITY_SERVICE_KEY], IntegrityService)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_integrity_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("integrity", start=False)
    await loader.async_stop_all(component_core)
