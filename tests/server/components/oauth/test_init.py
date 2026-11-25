"""Unit tests for `supernote.server.components.oauth.OAuthComponent`."""

from __future__ import annotations

from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_oauth_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("oauth")
    component = loader.get("oauth")
    assert isinstance(component, Component)
    assert component.domain == "oauth"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
