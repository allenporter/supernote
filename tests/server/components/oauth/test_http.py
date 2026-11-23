"""Unit tests for `supernote.server.components.oauth.http`."""

from __future__ import annotations

from supernote.server.components.http import HttpRegistrar
from supernote.server.components.oauth.http import async_setup_http
from supernote.server.core import ServerCore


async def test_oauth_http_platform_registers_asgi_resource_and_prefixes(
    component_core: ServerCore,
) -> None:
    registrar = HttpRegistrar()
    await async_setup_http(component_core, registrar)

    assert len(registrar.public_resources) == 1
    assert "/.well-known/oauth-authorization-server" in registrar.known_resource_paths
    assert registrar.public_prefixes == (
        "/login-bridge",
        "/authorize",
        "/token",
        "/.well-known/",
    )
