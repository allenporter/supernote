from urllib.parse import urlparse

from supernote.client.client import Client
from supernote.client.device import DeviceClient


async def test_upload_file(
    device_client: DeviceClient,
    authenticated_client: Client,
) -> None:
    filename = "test_upload.note"
    file_content = b"some binary content"

    # Upload data
    upload_response = await device_client.upload_content(
        path=f"/{filename}", content=file_content, equipment_no="SN_TEST"
    )
    assert upload_response.id

    # Use file ID from upload response and request download
    file_id = int(upload_response.id)
    download_info = await device_client.download_v3(file_id, "SN_TEST")

    # Parse URL - simplistic since it returns full URL
    parsed = urlparse(download_info.url)
    path_qs = parsed.path + ("?" + parsed.query if parsed.query else "")

    resp = await authenticated_client.get(path_qs)
    assert resp.status == 200
    assert await resp.read() == file_content


async def test_chunked_upload(
    device_client: DeviceClient,
    authenticated_client: Client,
) -> None:
    """Test uploading a file in multiple chunks."""

    filename = "chunked_test.note"
    # Create content that will be chunked
    full_content = b"chunk data " * 300  # few KB

    await device_client.upload_content(
        path=f"/{filename}",
        content=full_content,
        equipment_no="SN_TEST",
        chunk_size=1024,  # Approx 4+ chunks
    )

    # Verify via download
    query_res = await device_client.query_by_path(f"/{filename}", "SN_TEST")
    assert query_res.entries_vo is not None
    file_id = int(query_res.entries_vo.id)

    # Download
    download_info = await device_client.download_v3(file_id, "SN_TEST")

    parsed = urlparse(download_info.url)
    path_qs = parsed.path + ("?" + parsed.query if parsed.query else "")

    resp = await authenticated_client.get(path_qs)
    assert resp.status == 200
    assert await resp.read() == full_content
