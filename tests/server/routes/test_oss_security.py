import urllib.parse

from supernote.client.client import Client
from supernote.client.device import DeviceClient


async def test_oss_download_public_access_flow(
    authenticated_client: Client,
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify entire flow of public OSS download with signature."""

    # Upload a file as authenticated user
    path = "/oss_security_test.txt"
    content = b"Security Test Content"
    upload_result = await device_client.upload_content(
        path=path, content=content, equipment_no="TEST"
    )
    assert upload_result.id
    file_id = int(upload_result.id)

    # Generate a signed url
    download_info = await device_client.download_v3(file_id, "TEST")
    assert download_info
    signed_url = download_info.url

    # Access with authenticated client
    resp_bytes = await authenticated_client.get_content(signed_url)
    assert resp_bytes == content

    # Access with UNauthenticated client (the signature should give access)
    # Extract relative path from signed_url for test client
    parsed = urllib.parse.urlparse(signed_url)
    relative_url = f"{parsed.path}?{parsed.query}"

    resp_public = await client.get(relative_url, headers={})
    assert resp_public.status == 200
    assert await resp_public.read() == content
