"""Unit tests for `supernote.server.components.socketio`."""

from __future__ import annotations

from supernote.server.components.socketio import (
    SOCKETIO_MANAGER_KEY,
    SocketIOComponent,
    SocketIOServerManager,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_socketio_component_lifecycle(component_core: ServerCore) -> None:
    component = SocketIOComponent()
    assert isinstance(component, Component)
    assert component.domain == "socketio"
    assert component.dependencies == ()
    assert component.platforms == ("http",)

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[SOCKETIO_MANAGER_KEY], SocketIOServerManager)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
