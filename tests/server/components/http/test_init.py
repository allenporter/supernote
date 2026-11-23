"""Unit tests for `supernote.server.components.http` (`HttpComponent` and `HttpRegistrar`)."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web

from supernote.server.components.http import (
    HTTP_REGISTRAR_KEY,
    HttpComponent,
    HttpRegistrar,
)
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@pytest.fixture
def http_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures."""
    return ServerCore(
        config=server_config,
        app=web.Application(),
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


def test_http_registrar_collects_middlewares_prefixes_and_resources() -> None:
    @web.middleware
    async def outer_mw(request: web.Request, handler: Any) -> web.StreamResponse:
        return await handler(request)

    @web.middleware
    async def inner_mw(request: web.Request, handler: Any) -> web.StreamResponse:
        return await handler(request)

    registrar = HttpRegistrar()
    registrar.add_middleware(outer_mw, pre_auth=True)
    registrar.add_middleware(inner_mw)
    registrar.add_public_prefix("/socket.io")
    registrar.add_public_prefix("/socket.io")

    assert registrar.outer_middlewares == (outer_mw,)
    assert registrar.inner_middlewares == (inner_mw,)
    assert registrar.public_prefixes == ("/socket.io",)

    with pytest.raises(ValueError, match="must start with '/'"):
        registrar.add_public_prefix("socket.io")

    resource = web.PlainResource("/oauth")
    registrar.add_public_resource(resource, known_paths=("/authorize", "/token"))
    registrar.add_public_resource(resource, known_paths=("/token",))

    assert registrar.public_resources == (resource,)
    assert registrar.known_resource_paths == frozenset({"/authorize", "/token"})

    app = web.Application()
    registrar.mount_resources(app)
    assert resource in list(app.router.resources())


async def test_http_component_lifecycle(http_core: ServerCore) -> None:
    component = HttpComponent()
    assert isinstance(component, Component)
    assert component.domain == "http"
    assert component.dependencies == ()
    assert component.platforms == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(http_core, {})
    assert isinstance(http_core.app[HTTP_REGISTRAR_KEY], HttpRegistrar)

    await loader.async_start_all(http_core)
    await loader.async_stop_all(http_core)
