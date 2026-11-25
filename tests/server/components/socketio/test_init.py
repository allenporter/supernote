"""Unit tests for `supernote.server.components.socketio`."""

from __future__ import annotations

from supernote.server.components.socketio import (
    SOCKETIO_MANAGER_KEY,
    SocketIOServerManager,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_socketio_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("socketio")
    component = loader.get("socketio")
    assert isinstance(component, Component)
    assert component.domain == "socketio"
    assert component.dependencies == ()
    assert component.platforms == ("http",)
    assert isinstance(component_core.app[SOCKETIO_MANAGER_KEY], SocketIOServerManager)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)
