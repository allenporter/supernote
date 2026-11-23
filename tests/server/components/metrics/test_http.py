"""Unit tests for `supernote.server.components.metrics.http`."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, make_mocked_request

from supernote.server.components.http import HttpRegistrar
from supernote.server.components.metrics.http import (
    _normalize_http_method,
    _resolve_metrics_path,
    async_setup_http,
)
from supernote.server.core import ServerCore


async def test_metrics_http_platform_registers_route_and_outer_middleware(
    component_core: ServerCore,
) -> None:
    registrar = HttpRegistrar()
    await async_setup_http(component_core, registrar)

    assert len(registrar.outer_middlewares) == 1
    paths = [r.canonical for r in component_core.app.router.resources()]
    assert component_core.config.metrics_path in paths


@pytest.mark.parametrize(
    ("raw_method", "expected"),
    [
        ("GET", "GET"),
        ("get", "GET"),
        ("HEAD", "HEAD"),
        ("POST", "POST"),
        ("PUT", "PUT"),
        ("DELETE", "DELETE"),
        ("OPTIONS", "OPTIONS"),
        ("PATCH", "PATCH"),
        ("PROPFIND", "OTHER"),
        ("SCANNER_VERB", "OTHER"),
    ],
)
def test_normalize_http_method_bounds_cardinality(
    raw_method: str,
    expected: str,
) -> None:
    """Verify _normalize_http_method preserves standard HTTP verbs and bounds arbitrary ones."""
    assert _normalize_http_method(raw_method) == expected


@pytest.mark.parametrize("mcp_enabled", [True])
async def test_resolve_metrics_path_preserves_known_mcp_auth_route(
    client: TestClient,
    mcp_enabled: bool,
) -> None:
    """Verify _resolve_metrics_path keeps canonical paths for known MCP OAuth routes."""
    assert client.app is not None
    known_req = make_mocked_request("GET", "/authorize", app=client.app)
    known_match_info = await client.app.router.resolve(known_req)
    known_match_info.add_app(client.app)
    known_req._match_info = known_match_info
    assert (
        _resolve_metrics_path(known_req, 302, frozenset({"/authorize"})) == "/authorize"
    )


@pytest.mark.parametrize("mcp_enabled", [True])
async def test_resolve_metrics_path_collapses_unknown_mcp_asgi_path(
    client: TestClient,
    mcp_enabled: bool,
) -> None:
    """Verify _resolve_metrics_path collapses unmatched paths routed to MCP ASGIResource."""
    assert client.app is not None
    unknown_req = make_mocked_request("GET", "/wp-login.php", app=client.app)
    unknown_match_info = await client.app.router.resolve(unknown_req)
    unknown_match_info.add_app(client.app)
    unknown_req._match_info = unknown_match_info
    assert (
        _resolve_metrics_path(unknown_req, 404, frozenset({"/authorize"})) == "HTTP 404"
    )


async def test_resolve_metrics_path_normalizes_static_route(
    client: TestClient,
) -> None:
    """Verify static asset routes normalize to '/static/{filename}'."""
    assert client.app is not None
    static_req = make_mocked_request("GET", "/static/app.js", app=client.app)
    static_match_info = await client.app.router.resolve(static_req)
    static_match_info.add_app(client.app)
    static_req._match_info = static_match_info
    assert _resolve_metrics_path(static_req, 200) == "/static/{filename}"


async def test_resolve_metrics_path_uses_route_formatter() -> None:
    """Verify parameterized routes resolve to their template formatter rather than raw IDs."""

    async def _item_handler(_r: web.Request) -> web.Response:
        return web.Response()

    dyn_app = web.Application()
    dyn_app.router.add_get("/test-items/{item_id}", _item_handler)
    dyn_req = make_mocked_request("GET", "/test-items/42", app=dyn_app)
    dyn_match_info = await dyn_app.router.resolve(dyn_req)
    dyn_match_info.add_app(dyn_app)
    dyn_req._match_info = dyn_match_info
    assert _resolve_metrics_path(dyn_req, 200) == "/test-items/{item_id}"


async def test_resolve_metrics_path_falls_back_when_resource_info_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resources with empty get_info() fall back to HTTP status."""

    async def _item_handler(_r: web.Request) -> web.Response:
        return web.Response()

    dyn_app = web.Application()
    dyn_app.router.add_get("/test-items/{item_id}", _item_handler)
    req = make_mocked_request("GET", "/custom/probe", app=dyn_app)
    match_info = await dyn_app.router.resolve(
        make_mocked_request("GET", "/test-items/42", app=dyn_app)
    )
    match_info.add_app(dyn_app)
    assert match_info.route.resource is not None
    monkeypatch.setattr(match_info.route.resource, "get_info", dict)
    req._match_info = match_info
    assert _resolve_metrics_path(req, 204) == "HTTP 204"
