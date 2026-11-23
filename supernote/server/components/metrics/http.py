"""HTTP platform setup for the Prometheus metrics component."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from collections.abc import Set as AbstractSet

from aiohttp import web
from aiohttp.typedefs import Middleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.keys import HTTP_REGISTRAR_KEY
from supernote.server.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)
from supernote.server.routes.decorators import public_route

__all__ = [
    "async_setup_http",
    "create_metrics_middleware",
    "metrics_middleware",
]

logger = logging.getLogger(__name__)

_KNOWN_HTTP_METHODS: frozenset[str] = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"}
)


def _normalize_http_method(method: str) -> str:
    """Normalize HTTP method to a bounded label set."""
    normalized = method.upper()
    return normalized if normalized in _KNOWN_HTTP_METHODS else "OTHER"


def _resolve_metrics_path(
    request: web.Request,
    status: int,
    mcp_auth_paths: AbstractSet[str] = frozenset(),
) -> str:
    """Resolve a bounded Prometheus path label without falling back to raw request paths."""
    route = request.match_info.route
    if route is None:
        return request.path if request.path in mcp_auth_paths else f"HTTP {status}"
    if route.resource is None:
        return f"HTTP {status}"
    if route.name == "static":
        return "/static/{filename}"
    info = route.resource.get_info()
    return info.get("formatter") or info.get("path") or f"HTTP {status}"


def create_metrics_middleware(
    metrics_path: str = "/metrics",
    mcp_auth_paths: AbstractSet[str] | None = None,
) -> Middleware:
    """Create HTTP Prometheus metrics middleware with explicit path configuration."""

    @web.middleware
    async def _middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.path == metrics_path:
            return await handler(request)

        method = _normalize_http_method(request.method)
        start_time = time.perf_counter()
        status = 500
        cancelled = False
        try:
            response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as ex:
            status = ex.status
            raise
        except asyncio.CancelledError:
            status = 499
            cancelled = True
            raise
        finally:
            duration = time.perf_counter() - start_time
            if mcp_auth_paths is not None:
                known_paths = mcp_auth_paths
            elif (http_registrar := request.app.get(HTTP_REGISTRAR_KEY)) is not None:
                known_paths = http_registrar.known_resource_paths
            else:
                known_paths = frozenset()
            path_pattern = _resolve_metrics_path(request, status, known_paths)
            HTTP_REQUESTS_TOTAL.labels(
                method=method, path=path_pattern, status=str(status)
            ).inc()
            if not cancelled:
                HTTP_REQUEST_DURATION_SECONDS.labels(
                    method=method, path=path_pattern
                ).observe(duration)

    return _middleware


metrics_middleware: Middleware = create_metrics_middleware()


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Expose the Prometheus scrape endpoint and register HTTP metrics middleware."""

    @public_route
    async def handle_metrics(request: web.Request) -> web.Response:
        data = generate_latest()
        return web.Response(body=data, headers={"Content-Type": CONTENT_TYPE_LATEST})

    core.app.router.add_get(core.config.metrics_path, handle_metrics)
    logger.info("Exposing Prometheus metrics at %s", core.config.metrics_path)
    registrar.add_middleware(
        create_metrics_middleware(metrics_path=core.config.metrics_path),
        pre_auth=True,
    )
