from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient
from prometheus_client import REGISTRY

from supernote.server import metrics as metrics_module
from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.metrics import (
    RECYCLE_BIN_CLEANUP_BYTES_FREED_TOTAL,
    RECYCLE_BIN_CLEANUP_DURATION_SECONDS,
    RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL,
    RECYCLE_BIN_CLEANUP_RUNS_TOTAL,
    STORAGE_CLEANUP_BYTES_RECLAIMED_TOTAL,
    STORAGE_CLEANUP_CHUNKS_REMOVED_TOTAL,
    STORAGE_CLEANUP_TEMP_FILES_REMOVED_TOTAL,
)
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


def test_metrics_exports() -> None:
    """Verify explicit __all__ exports of supernote.server.metrics."""
    assert hasattr(metrics_module, "__all__")
    expected = [
        "DB_SESSIONS_ACTIVE",
        "DB_SESSION_ERRORS_TOTAL",
        "GEMINI_API_CALLS_TOTAL",
        "GEMINI_API_DURATION_SECONDS",
        "HTTP_REQUESTS_TOTAL",
        "HTTP_REQUEST_DURATION_SECONDS",
        "PROCESSOR_FILES_PROCESSING",
        "PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL",
        "PROCESSOR_QUEUE_SIZE",
        "PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL",
        "PROCESSOR_TASKS_TOTAL",
        "PROCESSOR_TASK_DURATION_SECONDS",
        "RECYCLE_BIN_CLEANUP_BYTES_FREED_TOTAL",
        "RECYCLE_BIN_CLEANUP_DURATION_SECONDS",
        "RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL",
        "RECYCLE_BIN_CLEANUP_RUNS_TOTAL",
        "STORAGE_CLEANUP_BYTES_RECLAIMED_TOTAL",
        "STORAGE_CLEANUP_CHUNKS_REMOVED_TOTAL",
        "STORAGE_CLEANUP_TEMP_FILES_REMOVED_TOTAL",
    ]
    assert sorted(metrics_module.__all__) == sorted(expected)
    for name in expected:
        assert hasattr(metrics_module, name)


async def test_storage_cleanup_metrics_endpoint(client: TestClient) -> None:
    """Verify that storage cleanup metrics are exposed on the /metrics endpoint."""
    resp = await client.get("/metrics")
    assert resp.status == 200
    body = await resp.text()

    assert "supernote_storage_cleanup_temp_files_removed_total" in body
    assert "supernote_storage_cleanup_chunks_removed_total" in body
    assert "supernote_storage_cleanup_bytes_reclaimed_total" in body


async def test_storage_cleanup_metrics_tracking() -> None:
    """Verify that storage cleanup counter increments are reflected in REGISTRY sample values."""
    before_files = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_temp_files_removed_total")
        or 0.0
    )
    before_chunks = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_chunks_removed_total")
        or 0.0
    )
    before_bytes = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_bytes_reclaimed_total")
        or 0.0
    )

    STORAGE_CLEANUP_TEMP_FILES_REMOVED_TOTAL.inc(3)
    STORAGE_CLEANUP_CHUNKS_REMOVED_TOTAL.inc(5)
    STORAGE_CLEANUP_BYTES_RECLAIMED_TOTAL.inc(2048)

    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_temp_files_removed_total")
        == before_files + 3.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_chunks_removed_total")
        == before_chunks + 5.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_bytes_reclaimed_total")
        == before_bytes + 2048.0
    )


async def test_recycle_bin_cleanup_metrics_endpoint(client: TestClient) -> None:
    """Verify that recycle bin cleanup metrics are exposed on the /metrics endpoint."""
    resp = await client.get("/metrics")
    assert resp.status == 200
    body = await resp.text()

    assert "supernote_recycle_bin_cleanup_runs_total" in body
    assert "supernote_recycle_bin_cleanup_duration_seconds" in body
    assert "supernote_recycle_bin_cleanup_items_purged_total" in body
    assert "supernote_recycle_bin_cleanup_bytes_freed_total" in body


async def test_recycle_bin_cleanup_metrics_tracking() -> None:
    """Verify that recycle bin cleanup metric increments and observations are recorded."""
    before_runs = (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "success"}
        )
        or 0.0
    )
    before_items = (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_items_purged_total")
        or 0.0
    )
    before_bytes = (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_bytes_freed_total")
        or 0.0
    )

    RECYCLE_BIN_CLEANUP_RUNS_TOTAL.labels(status="success").inc(2)
    RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL.inc(7)
    RECYCLE_BIN_CLEANUP_BYTES_FREED_TOTAL.inc(4096)
    RECYCLE_BIN_CLEANUP_DURATION_SECONDS.observe(0.042)

    assert (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "success"}
        )
        == before_runs + 2.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_items_purged_total")
        == before_items + 7.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_bytes_freed_total")
        == before_bytes + 4096.0
    )
