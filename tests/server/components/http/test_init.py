"""Unit tests for `supernote.server.components.http` (`HttpComponent` and `HttpRegistrar`)."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from supernote.server.components.http import (
    HTTP_REGISTRAR_KEY,
    HttpComponent,
    HttpRegistrar,
    jwt_auth_middleware,
)
from supernote.server.core import Component, ComponentError, ComponentLoader, ServerCore
from supernote.server.keys import CONFIG_KEY
from supernote.server.routes.decorators import public_route
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


async def test_add_extension_routes_enforces_domain_prefix_and_auth(
    component_core: ServerCore,
) -> None:
    registrar = HttpRegistrar()
    app = component_core.app
    app[CONFIG_KEY] = component_core.config
    routes = web.RouteTableDef()

    @routes.get("/api/ext/demo")
    async def root_handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    @routes.get("/api/ext/demo/public")
    @public_route
    async def public_handler(request: web.Request) -> web.Response:
        return web.json_response({"public": True})

    registrar.add_extension_routes(app, "demo", routes)
    registrar.apply_to_app(app)

    async with TestClient(TestServer(app)) as client:
        resp_protected = await client.get("/api/ext/demo")
        assert resp_protected.status == 401
        resp_public = await client.get("/api/ext/demo/public")
        assert resp_public.status == 200
        assert await resp_public.json() == {"public": True}


@pytest.mark.parametrize(
    "bad_path",
    [
        "/api/file/2/list",
        "/api/ext/other/ping",
        "/api/ext/demo2/ping",
        "/api/ext/demo/../secret",
    ],
)
def test_add_extension_routes_rejects_out_of_prefix_atomically(
    bad_path: str,
) -> None:
    registrar = HttpRegistrar()
    app = web.Application()
    routes = web.RouteTableDef()

    @routes.get("/api/ext/demo/valid")
    async def ok_handler(request: web.Request) -> web.Response:
        return web.Response()

    @routes.get(bad_path)
    async def bad_handler(request: web.Request) -> web.Response:
        return web.Response()

    with pytest.raises(ComponentError, match="/api/ext/demo/"):
        registrar.add_extension_routes(app, "demo", routes)

    assert list(app.router.resources()) == []


def test_add_extension_routes_rejects_static_def_and_invalid_domain() -> None:
    registrar = HttpRegistrar()
    app = web.Application()
    routes = web.RouteTableDef()
    routes.static("/api/ext/demo/static", ".")

    with pytest.raises(ComponentError, match="HTTP route definitions"):
        registrar.add_extension_routes(app, "demo", routes)

    with pytest.raises(ComponentError, match="must match"):
        registrar.add_extension_routes(app, "../bad", web.RouteTableDef())
