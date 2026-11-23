"""Unit tests for `supernote.server.components.http` (`HttpComponent` and `HttpRegistrar`)."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web

from supernote.server.components.http import (
    HTTP_REGISTRAR_KEY,
    HttpComponent,
    HttpRegistrar,
    jwt_auth_middleware,
)
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.trace import trace_middleware


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
    registrar.apply_to_app(app)
    # mount_resources is idempotent on repeat calls
    registrar.mount_resources(app)
    assert list(app.router.resources()).count(resource) == 1
    assert list(app.middlewares) == [
        outer_mw,
        trace_middleware,
        jwt_auth_middleware,
        inner_mw,
    ]


async def test_http_component_lifecycle(component_core: ServerCore) -> None:
    component = HttpComponent()
    assert isinstance(component, Component)
    assert component.domain == "http"
    assert component.dependencies == ()
    assert component.platforms == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[HTTP_REGISTRAR_KEY], HttpRegistrar)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
