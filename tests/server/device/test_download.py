from urllib.parse import urlparse

from supernote.client import Client
from supernote.client.device import DeviceClient


async def test_download_file_with_spaces(
    authenticated_client: Client,
    device_client: DeviceClient,
) -> None:
    # Create a test file with spaces
    filename = "2023 December.pdf"
    full_filename = f"EXPORT/{filename}"
    await device_client.upload_content(
        path=full_filename, content="pdf content", equipment_no="SN123"
    )

    # Obtain a download URL
    # Resolve ID
    query_resp = await device_client.query_by_path(
        path=full_filename, equipment_no="SN123"
    )
    assert query_resp.entries_vo is not None
    real_id = int(query_resp.entries_vo.id)

    data = await device_client.download_v3(file_id=real_id, equipment_no="SN123")

    # Download the file
    download_url = urlparse(data.url)
    download_url_str = download_url.path + "?" + download_url.query

    resp = await authenticated_client.get(download_url_str)
    assert resp.status == 200
    content = await resp.read()
    assert content == b"pdf content"
