"""Test that proxy mode is disabled by default."""
from aiohttp.test_utils import TestClient

from supernote.models.file import FileUploadApplyLocalDTO


async def test_proxy_headers_ignored_by_default(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that proxy headers are ignored when proxy_mode is None (default)."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_default.note",
        path="/",
        size=1234,
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
    assert "http://127.0.0.1" in full_upload_url or "http://localhost" in full_upload_url
