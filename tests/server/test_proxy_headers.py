"""Tests for proxy header handling.

These tests verify that the server correctly handles X-Forwarded-* headers
when deployed behind a reverse proxy.

Note: Tests for 'disabled' and 'strict' proxy modes would require creating
separate app instances with different configurations, which conflicts with
the shared session_manager fixture. The default 'relaxed' mode is tested here,
and strict/disabled modes can be verified through manual testing or integration
tests with separate server instances.
"""

import pytest
from aiohttp.test_utils import TestClient

from supernote.models.file import FileUploadApplyLocalDTO


@pytest.fixture
def proxy_mode() -> str:
    """Override default proxy_mode to 'relaxed' for these tests."""
    return "relaxed"


async def test_upload_url_proxy_headers_relaxed(
    client: TestClient, auth_headers: dict[str, str]
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


async def test_upload_url_no_proxy_headers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that upload URLs work without proxy headers."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_no_proxy.note",
        path="/",
        size=1234,
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


async def test_upload_url_with_port_in_forwarded_host(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that upload URLs respect X-Forwarded-Host with port."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_port.note",
        path="/",
        size=1234,
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
