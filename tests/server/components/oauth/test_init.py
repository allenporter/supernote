"""Unit tests for `supernote.server.components.oauth.OAuthComponent`."""

from __future__ import annotations

from supernote.server.components.oauth import OAuthComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_oauth_component_lifecycle(component_core: ServerCore) -> None:
    component = OAuthComponent()
    assert isinstance(component, Component)
    assert component.domain == "oauth"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
