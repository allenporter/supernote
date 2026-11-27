"""Unit tests for `ConfigComponent` lifecycle and app key wiring."""

from __future__ import annotations

from supernote.server.components.config import ConfigComponent
from supernote.server.components.config.service import (
    CONFIG_SERVICE_KEY,
    ConfigService,
)
from supernote.server.core import ServerCore


async def test_config_component_setup_and_stop(component_core: ServerCore) -> None:
    """`ConfigComponent` registers `ConfigService` on `core.app` during setup."""
    comp = ConfigComponent()
    assert comp.domain == "config"
    assert comp.dependencies == ()
    assert comp.platforms == ("http",)

    await comp.async_setup(component_core, {})
    assert isinstance(component_core.app[CONFIG_SERVICE_KEY], ConfigService)

    await comp.async_start(component_core)
    await comp.async_stop(component_core)
