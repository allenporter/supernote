"""HTTP platform tests for `supernote.server.components.web_ui.http`."""

from __future__ import annotations

from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.server.core import ServerCore
from supernote.server.routes.decorators import public_route
from tests.server.components.conftest import LoadComponents


async def test_web_ui_http_platform_serves_public_assets_with_no_cache(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    @public_route
    async def handle_health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    component_core.app.router.add_get("/api/health", handle_health)
    await load_components("http", "web_ui")
    client = await aiohttp_client(component_core.app)

    root_resp = await client.get("/")
    assert root_resp.status == 200
    assert root_resp.headers.get("Cache-Control") == "no-cache"

    static_resp = await client.get("/static/style.css")
    assert static_resp.status == 200
    assert static_resp.headers.get("Cache-Control") == "no-cache"

    api_resp = await client.get("/api/health")
    assert api_resp.status == 200
    assert "Cache-Control" not in api_resp.headers
