"""Unit tests for `supernote.server.components.web_ui.WebUiComponent`."""

from __future__ import annotations

from supernote.server.components.web_ui import WebUiComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_web_ui_component_lifecycle(component_core: ServerCore) -> None:
    component = WebUiComponent()
    assert isinstance(component, Component)
    assert component.domain == "web_ui"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
