"""HTTP platform tests for `supernote.server.components.socketio.http`."""

from __future__ import annotations

from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.server.core import ServerCore
from supernote.server.routes.decorators import public_route
from tests.server.components.conftest import LoadComponents


async def test_socketio_http_platform_serves_public_eio3_compat_without_mutating_other_routes(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    @public_route
    async def handle_health(request: web.Request) -> web.Response:
        return web.Response(text=request.query.get("EIO", ""))

    component_core.app.router.add_get("/api/health", handle_health)
    await load_components("http", "socketio")
    client = await aiohttp_client(component_core.app)

    # EIO=3 polling handshake on /socket.io/ is publicly accessible and rewritten to EIO=4.
    sio_resp = await client.get("/socket.io/?EIO=3&transport=polling")
    assert sio_resp.status == 200
    body = await sio_resp.text()
    assert body.startswith("0{")

    # Non-/socket.io/ routes preserve EIO=3 untouched.
    health_resp = await client.get("/api/health?EIO=3")
    assert health_resp.status == 200
    assert await health_resp.text() == "3"
