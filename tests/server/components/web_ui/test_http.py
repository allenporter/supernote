"""Unit tests for `supernote.server.components.web_ui.http`."""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from supernote.server.components.http import HttpRegistrar
from supernote.server.components.web_ui.http import (
    async_setup_http,
    static_cache_control_middleware,
)
from supernote.server.core import ServerCore


async def test_web_ui_http_platform_mounts_index_static_and_cache_middleware(
    component_core: ServerCore,
) -> None:
    registrar = HttpRegistrar()
    await async_setup_http(component_core, registrar)

    assert registrar.public_prefixes == ("/static/", "/favicon.ico")
    assert registrar.inner_middlewares == (static_cache_control_middleware,)
    paths = [r.canonical for r in component_core.app.router.resources()]
    assert "/" in paths
    assert "/static" in paths


async def test_static_cache_control_middleware_sets_no_cache_on_static_paths() -> None:
    async def handler(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    root_resp = await static_cache_control_middleware(
        make_mocked_request("GET", "/"), handler
    )
    assert root_resp.headers.get("Cache-Control") == "no-cache"

    static_resp = await static_cache_control_middleware(
        make_mocked_request("GET", "/static/js/main.js"), handler
    )
    assert static_resp.headers.get("Cache-Control") == "no-cache"

    api_resp = await static_cache_control_middleware(
        make_mocked_request("GET", "/api/health"), handler
    )
    assert "Cache-Control" not in api_resp.headers
