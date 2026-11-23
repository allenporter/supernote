"""HTTP platform setup for the OAuth 2.1 Authorization Server."""

from __future__ import annotations

import logging

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore

__all__ = ["async_setup_http"]

logger = logging.getLogger(__name__)

_OAUTH_PUBLIC_PREFIXES = (
    "/login-bridge",
    "/authorize",
    "/token",
    "/.well-known/",
)


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register the OAuth 2.1 ASGI resource, public prefixes, and metrics paths."""
    from aiohttp_asgi import ASGIResource  # noqa: PLC0415

    from .provider import create_auth_app  # noqa: PLC0415

    logger.info("Mounting OAuth 2.1 Authorization Server at %s", core.config.base_url)
    auth_app = create_auth_app(
        core.user_service,
        core.coordination,
        core.config.base_url,
    )
    asgi_resource = ASGIResource(auth_app)
    known_paths = (
        path
        for route in auth_app.routes
        if isinstance(path := getattr(route, "path", None), str)
    )
    registrar.add_public_resource(asgi_resource, known_paths=known_paths)
    for prefix in _OAUTH_PUBLIC_PREFIXES:
        registrar.add_public_prefix(prefix)
