"""HTTP platform setup for the Web UI static SPA component."""

from __future__ import annotations

import importlib.resources
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.routes.decorators import public_route

__all__ = ["async_setup_http", "static_cache_control_middleware"]


@web.middleware
async def static_cache_control_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Ensure frontend HTML and static assets revalidate across server upgrades."""
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Mount `/` and `/static/`, exempt static paths from auth, and register cache control."""
    static_path = Path(str(importlib.resources.files("supernote.server") / "static"))

    @public_route
    async def handle_index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(
            static_path / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    async def handle_web_features(request: web.Request) -> web.Response:
        _ = request
        return web.json_response(
            {"wiki_enabled": bool(core.config.wiki.get("enabled", False))}
        )

    registrar.router.add_get("/", handle_index)
    registrar.router.add_get("/api/extended/web/features", handle_web_features)
    registrar.router.add_static("/static/", path=static_path, name="static")
    registrar.add_public_prefix("/static/")
    registrar.add_middleware(static_cache_control_middleware)
