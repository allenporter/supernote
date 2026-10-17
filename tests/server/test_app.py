"""Tests for application-level functionality including proxy header handling.

These tests verify that the server correctly handles X-Forwarded-* headers
when deployed behind a reverse proxy, with different proxy modes.
"""

import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.models.file_device import FileUploadApplyLocalDTO
from supernote.server import app as app_module
from supernote.server.app import create_app
from supernote.server.config import ServerConfig


def test_import_does_not_load_google_genai() -> None:
    """Importing the server bootstrap module should not eagerly import
    `google-genai` (see issue #106).

    `google-genai` is only needed once a Gemini API key is configured. Run
    in a subprocess so the check isn't polluted by other tests in this
    session having already imported the module.
    """
    check = (
        "import sys; import supernote.server.app; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m == 'google.genai' or m.startswith('google.genai.')"
        "); "
        "print(','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"google-genai modules unexpectedly loaded: {result.stdout.strip()}"
    )


# Test for default proxy mode (disabled)
async def test_proxy_headers_ignored_by_default(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that proxy headers are ignored when proxy_mode is None (default)."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_default.note",
        path="/",
        size="1234",
    ).to_dict()

    # Send proxy headers (should be ignored)
    proxy_headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "malicious-domain.com",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should NOT use forwarded headers, should use actual test client host
    assert not full_upload_url.startswith("https://malicious-domain.com"), (
        f"Proxy headers should be ignored by default, got: {full_upload_url}"
    )
    # Should use the test server's actual scheme and host
    assert (
        "http://127.0.0.1" in full_upload_url or "http://localhost" in full_upload_url
    )


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_proxy_headers_relaxed(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs respect X-Forwarded headers in relaxed mode."""

    # Payload for upload apply
    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_proxy.note",
        path="/",
        size="1234",
    ).to_dict()

    # Headers mocking a proxy
    proxy_headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "my-public-domain.com",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Verification: Should use forwarded headers
    assert full_upload_url.startswith("https://my-public-domain.com"), (
        f"Got URL: {full_upload_url}"
    )


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_no_proxy_headers(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs work without proxy headers."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_no_proxy.note",
        path="/",
        size="1234",
    ).to_dict()

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=auth_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should use the test client's host (127.0.0.1 or similar)
    assert "http://127.0.0.1:" in full_upload_url


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_with_port_in_forwarded_host(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs respect X-Forwarded-Host with port."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_port.note",
        path="/",
        size="1234",
    ).to_dict()

    # Headers with port in host
    proxy_headers = {
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "localhost:9888",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should use forwarded host with port
    assert full_upload_url.startswith("http://localhost:9888"), (
        f"Got URL: {full_upload_url}"
    )


async def test_static_frontend_sha256_fallback(client: TestClient) -> None:
    """Verify that index.html and client.js include fallback for SHA-256 in insecure contexts."""
    resp = await client.get("/")
    assert resp.status == 200
    html = await resp.text()
    assert "js-sha256" in html

    resp = await client.get("/static/js/api/client.js")
    assert resp.status == 200
    js = await resp.text()
    assert "crypto.subtle" in js
    assert "window.sha256" in js


def test_app_exports() -> None:
    """Verify explicit __all__ exports of supernote.server.app."""
    assert hasattr(app_module, "__all__")
    expected = [
        "bootstrap_ephemeral_user",
        "create_app",
        "create_coordination_service",
        "create_db_session_manager",
        "is_binary_content_type",
        "jwt_auth_middleware",
        "metrics_middleware",
        "run",
        "socketio_compat_middleware",
        "trace_middleware",
        "try_parse_json",
    ]
    assert sorted(app_module.__all__) == sorted(expected)
    for name in expected:
        assert hasattr(app_module, name)


async def test_app_cleanup_service_di(server_config: ServerConfig) -> None:
    """Verify StorageCleanupService receives primitive config parameters and FileService is initialized without storage_root."""
    server_config.storage_cleanup_interval_seconds = 7200
    server_config.storage_temp_ttl_seconds = 172800

    app = create_app(server_config)

    file_service = app["file_service"]
    assert file_service is not None
    assert not hasattr(file_service, "storage_root")

    cleanup_service = app["storage_cleanup_service"]
    assert cleanup_service is not None
    assert cleanup_service.interval_seconds == 7200
    assert cleanup_service.temp_ttl_seconds == 172800


async def test_storage_cleanup_lifespan_enabled(
    server_config: ServerConfig,
    aiohttp_client: Any,
) -> None:
    """Verify StorageCleanupService starts and stops cleanly with app lifespan when enabled."""
    server_config.storage_cleanup_enabled = True
    app = create_app(server_config)
    cleanup_service = app["storage_cleanup_service"]

    with (
        patch.object(
            cleanup_service, "start", wraps=cleanup_service.start
        ) as mock_start,
        patch.object(cleanup_service, "stop", wraps=cleanup_service.stop) as mock_stop,
    ):
        client = await aiohttp_client(app)
        mock_start.assert_awaited_once()
        assert cleanup_service._polling_task is not None
        assert not cleanup_service._polling_task.done()

        await client.close()
        mock_stop.assert_awaited_once()
        assert cleanup_service._polling_task is None


async def test_storage_cleanup_lifespan_disabled(
    server_config: ServerConfig,
    aiohttp_client: Any,
) -> None:
    """Verify StorageCleanupService is not started or stopped when storage_cleanup_enabled is False."""
    server_config.storage_cleanup_enabled = False
    app = create_app(server_config)
    cleanup_service = app["storage_cleanup_service"]

    with (
        patch.object(
            cleanup_service, "start", wraps=cleanup_service.start
        ) as mock_start,
        patch.object(cleanup_service, "stop", wraps=cleanup_service.stop) as mock_stop,
    ):
        client = await aiohttp_client(app)
        mock_start.assert_not_called()
        assert cleanup_service._polling_task is None

        await client.close()
        mock_stop.assert_not_called()


async def test_recycle_bin_cleanup_lifespan_enabled(
    server_config: ServerConfig,
    aiohttp_client: Any,
) -> None:
    """Verify RecycleBinCleanupService starts and stops cleanly with app lifespan when enabled."""
    server_config.recycle_bin_cleanup_enabled = True
    app = create_app(server_config)
    cleanup_service = app["recycle_bin_cleanup_service"]

    with (
        patch.object(
            cleanup_service, "start", wraps=cleanup_service.start
        ) as mock_start,
        patch.object(cleanup_service, "stop", wraps=cleanup_service.stop) as mock_stop,
    ):
        client = await aiohttp_client(app)
        mock_start.assert_awaited_once()
        assert cleanup_service._polling_task is not None
        assert not cleanup_service._polling_task.done()

        await client.close()
        mock_stop.assert_awaited_once()
        assert cleanup_service._polling_task is None


async def test_recycle_bin_cleanup_lifespan_disabled(
    server_config: ServerConfig,
    aiohttp_client: Any,
) -> None:
    """Verify RecycleBinCleanupService is not started or stopped when recycle_bin_cleanup_enabled is False."""
    server_config.recycle_bin_cleanup_enabled = False
    app = create_app(server_config)
    cleanup_service = app["recycle_bin_cleanup_service"]

    with (
        patch.object(
            cleanup_service, "start", wraps=cleanup_service.start
        ) as mock_start,
        patch.object(cleanup_service, "stop", wraps=cleanup_service.stop) as mock_stop,
    ):
        client = await aiohttp_client(app)
        mock_start.assert_not_called()
        assert cleanup_service._polling_task is None

        await client.close()
        mock_stop.assert_not_called()
