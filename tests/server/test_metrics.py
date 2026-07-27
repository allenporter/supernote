from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient
from prometheus_client import REGISTRY

from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.services.gemini import GeminiService


async def test_metrics_endpoint(client: TestClient) -> None:
    """Verify that the metrics endpoint is exposed and returns Prometheus format."""
    resp = await client.get("/metrics")
    assert resp.status == 200
    assert "text/plain" in resp.headers["Content-Type"]

    body = await resp.text()
    # Should contain Python runtime or process metrics
    assert (
        "python_gc_objects_collected_total" in body
        or "process_cpu_seconds_total" in body
    )
    # Should contain our custom metrics
    assert "supernote_http_requests_total" in body


async def test_http_request_tracking(client: TestClient) -> None:
    """Verify that HTTP requests increment the request counters."""
    # Record current metric value
    before = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": "/api/file/query/server", "status": "200"},
        )
        or 0.0
    )

    resp = await client.get("/api/file/query/server")
    assert resp.status == 200

    after = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": "/api/file/query/server", "status": "200"},
        )
        or 0.0
    )

    assert after == before + 1.0


async def test_metrics_disabled(
    server_config: ServerConfig, aiohttp_client: Any
) -> None:
    """Verify that the metrics endpoint is not registered when metrics_enabled is False."""
    server_config.metrics_enabled = False

    app = create_app(server_config)
    client = await aiohttp_client(app)

    resp = await client.get("/metrics")
    assert resp.status == 404


async def test_db_session_metrics(client: TestClient) -> None:
    """Verify that DatabaseSessionManager correctly tracks session open/close and errors."""
    session_manager = client.app["session_manager"]

    # Verify active session count increases inside context manager
    before = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0

    async with session_manager.session():
        active_inside = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0
        assert active_inside == before + 1.0

    after = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0
    assert after == before

    # Verify session error count increases on database/sqlalchemy errors
    errors_before = (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    )

    with pytest.raises(Exception):
        async with session_manager.session():
            raise ValueError("Test error causing rollback")

    errors_after = REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    assert errors_after == errors_before + 1.0


async def test_gemini_service_metrics() -> None:
    """Verify that GeminiService tracks api call counts and durations."""
    gemini = GeminiService(api_key="mock-api-key")

    # Mock model API client
    mock_response = AsyncMock()
    gemini._client = AsyncMock()
    gemini._client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    gemini._client.aio.models.embed_content = AsyncMock(return_value=mock_response)

    before_calls = (
        REGISTRY.get_sample_value(
            "supernote_gemini_api_calls_total",
            {"operation": "generate_content", "status": "success"},
        )
        or 0.0
    )

    await gemini.generate_content(model="gemini-3-flash-preview", contents="hello")

    after_calls = (
        REGISTRY.get_sample_value(
            "supernote_gemini_api_calls_total",
            {"operation": "generate_content", "status": "success"},
        )
        or 0.0
    )

    assert after_calls == before_calls + 1.0

    # Test error tracking
    gemini._client.aio.models.generate_content.side_effect = Exception("API failure")

    before_fail_calls = (
        REGISTRY.get_sample_value(
            "supernote_gemini_api_calls_total",
            {"operation": "generate_content", "status": "failure"},
        )
        or 0.0
    )

    with pytest.raises(Exception):
        await gemini.generate_content(model="gemini-3-flash-preview", contents="hello")

    after_fail_calls = (
        REGISTRY.get_sample_value(
            "supernote_gemini_api_calls_total",
            {"operation": "generate_content", "status": "failure"},
        )
        or 0.0
    )

    assert after_fail_calls == before_fail_calls + 1.0
