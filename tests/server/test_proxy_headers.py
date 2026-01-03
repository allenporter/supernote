import pytest
from aiohttp.test_utils import TestClient

from supernote.models.file import FileUploadApplyLocalDTO


@pytest.mark.asyncio
async def test_upload_url_proxy_headers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that upload URLs respect X-Forwarded headers."""

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
        # X-Forwarded-Port is often inferred or optional, but X-Forwarded-Host usually contains port if non-standard.
        # aiohttp-remotes should handle Host and Scheme.
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Verification
    # Expected: https://my-public-domain.com/...
    assert full_upload_url.startswith("https://my-public-domain.com"), (
        f"Got URL: {full_upload_url}"
    )
