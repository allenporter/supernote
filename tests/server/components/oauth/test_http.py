"""HTTP platform tests for `supernote.server.components.oauth.http`."""

from __future__ import annotations

from pytest_aiohttp import AiohttpClient

from supernote.server.core import ServerCore
from tests.server.components.conftest import LoadComponents


async def test_oauth_http_platform_serves_public_discovery_metadata(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)

    resp = await client.get("/.well-known/oauth-authorization-server")
    assert resp.status == 200
    metadata = await resp.json()
    assert metadata["issuer"].rstrip("/") == component_core.config.base_url.rstrip("/")
    assert "authorization_endpoint" in metadata
    assert "token_endpoint" in metadata
