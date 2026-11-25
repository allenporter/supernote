"""Unit tests for `supernote.server.components.web_ui.WebUiComponent`."""

from __future__ import annotations

from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_web_ui_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("web_ui")
    component = loader.get("web_ui")
    assert isinstance(component, Component)
    assert component.domain == "web_ui"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
