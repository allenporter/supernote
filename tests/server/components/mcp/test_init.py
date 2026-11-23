"""Unit tests for `supernote.server.components.mcp.McpComponent`."""

from __future__ import annotations

from supernote.server.components.mcp import McpComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_mcp_component_lifecycle(component_core: ServerCore) -> None:
    component = McpComponent()
    assert isinstance(component, Component)
    assert component.domain == "mcp"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_mcp_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(McpComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
