"""Unit tests for `supernote.server.components.web_ui.WebUiComponent`."""

from __future__ import annotations

from supernote.server.components.web_ui import WEB_UI_CONFIG_KEY
from supernote.server.components.web_ui.config import WebUiConfig
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_web_ui_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components(
        "web_ui",
        configs={"web_ui": {"notebook_preview": False}},
    )
    component = loader.get("web_ui")
    assert isinstance(component, Component)
    assert component.domain == "web_ui"
    assert component.dependencies == ()
    assert component.platforms == ("http",)
    assert component_core.app[WEB_UI_CONFIG_KEY] == WebUiConfig(
        enabled=True,
        notebook_preview=False,
    )

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
