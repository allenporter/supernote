import os
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


async def test_upload_apply_response_fields(device_client: DeviceClient) -> None:
    """Test that upload/apply response contains expected fields for device compatibility."""
    filename = "field_test.note"
    path = f"/{filename}"
    content = b"test content"
    size = len(content)
    equipment_no = "SN_TEST"

    apply_response = await device_client.upload_apply(
        filename, path, size, equipment_no
    )

    # Verify fields match reference implementation requirements
    assert apply_response.bucket_name == filename
    assert apply_response.x_amz_date is not None
    assert int(apply_response.x_amz_date) > 0
    assert apply_response.authorization is not None
    assert "eyJ" in apply_response.authorization  # JWT start
    assert apply_response.full_upload_url is not None
    assert f"signature={apply_response.authorization}" in apply_response.full_upload_url
    assert f"timestamp={apply_response.x_amz_date}" in apply_response.full_upload_url
    assert apply_response.inner_name is not None
    assert apply_response.inner_name != filename

    # Verify Inner Name Format: {UUID}-{Tail}.{Ext}
    # Expected Tail for "SN_TEST" is "EST"
    name_part, ext_part = os.path.splitext(apply_response.inner_name)
    assert ext_part == ".note"

    # name_part should be UUID-Tail
    # UUID is 8-4-4-4-12 hex chars.
    parts = name_part.rsplit("-", 1)
    assert len(parts) == 2
    uuid_part, tail_part = parts
    assert len(uuid_part) == 36  # Standard UUID length
    assert tail_part == "EST"
