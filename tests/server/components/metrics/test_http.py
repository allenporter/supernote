"""HTTP platform tests for `supernote.server.components.metrics.http`."""

from __future__ import annotations

from aiohttp import web
from prometheus_client import REGISTRY
from pytest_aiohttp import AiohttpClient

from supernote.server.core import ServerCore
from supernote.server.routes.decorators import public_route
from tests.server.components.conftest import LoadComponents


def _http_request_count(method: str, path: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": method, "path": path, "status": status},
        )
        or 0.0
    )


async def test_metrics_http_platform_exposes_scrape_endpoint_and_normalizes_labels(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    """Verify `/metrics` is publicly served and HTTP middleware records bounded method/path labels."""

    @public_route
    async def handle_item(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    component_core.app.router.add_route("*", "/test-items/{item_id}", handle_item)

    before_item = _http_request_count("GET", "/test-items/{item_id}", "200")
    before_other_method = _http_request_count("OTHER", "/test-items/{item_id}", "200")
    before_static = _http_request_count("GET", "/static/{filename}", "200")
    before_oauth = _http_request_count(
        "GET", "/.well-known/oauth-authorization-server", "200"
    )
    before_unknown = _http_request_count("GET", "HTTP 404", "404")
    before_metrics = _http_request_count("GET", "/metrics", "200")

    await load_components("http", "metrics", "web_ui", "oauth")
    client = await aiohttp_client(component_core.app)

    resp = await client.get("/test-items/42")
    assert resp.status == 200

    resp_propfind = await client.request("PROPFIND", "/test-items/42")
    assert resp_propfind.status == 200

    resp_static = await client.get("/static/style.css")
    assert resp_static.status == 200

    resp_oauth = await client.get("/.well-known/oauth-authorization-server")
    assert resp_oauth.status == 200

    resp_unknown = await client.get("/wp-login.php")
    assert resp_unknown.status == 404

    resp_metrics = await client.get("/metrics")
    assert resp_metrics.status == 200
    metrics_text = await resp_metrics.text()
    assert "supernote_http_requests_total" in metrics_text

    assert (
        _http_request_count("GET", "/test-items/{item_id}", "200") == before_item + 1.0
    )
    assert _http_request_count("GET", "/test-items/42", "200") == 0.0
    assert (
        _http_request_count("OTHER", "/test-items/{item_id}", "200")
        == before_other_method + 1.0
    )
    assert (
        _http_request_count("GET", "/static/{filename}", "200") == before_static + 1.0
    )
    assert (
        _http_request_count("GET", "/.well-known/oauth-authorization-server", "200")
        == before_oauth + 1.0
    )
    assert _http_request_count("GET", "HTTP 404", "404") == before_unknown + 1.0
    assert _http_request_count("GET", "/wp-login.php", "404") == 0.0
    assert _http_request_count("GET", "/metrics", "200") == before_metrics
