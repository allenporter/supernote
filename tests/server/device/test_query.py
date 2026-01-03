import hashlib

from supernote.client.device import DeviceClient


async def test_query_v3_success(
    device_client: DeviceClient,
) -> None:
    """Query by ID and path."""
    # Create a test file
    content = b"some content"
    expected_hash = hashlib.md5(content).hexdigest()
    upload_response = await device_client.upload_content(
        "Note/test.note", content, equipment_no="SN123"
    )
    assert upload_response.id
    assert upload_response.path_display == "/Note/test.note"
    assert upload_response.name == "test.note"
    assert upload_response.content_hash == expected_hash

    # Query by ID (resolve first)
    path_str = "Note/test.note"
    # Resolve valid ID using query_by_path
    path_resp = await device_client.query_by_path(path=path_str, equipment_no="SN123")
    assert path_resp.entries_vo
    assert path_resp.entries_vo.path_display == "/Note/test.note"
    assert path_resp.entries_vo.name == "test.note"
    assert path_resp.entries_vo.content_hash == expected_hash
    assert path_resp.entries_vo.is_downloadable
    assert path_resp.entries_vo.id == upload_response.id

    # Now Query by strict ID
    data = await device_client.query_by_id(
        file_id=int(upload_response.id), equipment_no="SN123"
    )

    assert data.entries_vo
    assert data.entries_vo.id == upload_response.id
    assert data.entries_vo.name == "test.note"
    assert data.entries_vo.path_display == "/Note/test.note"
    assert data.entries_vo.content_hash == expected_hash


async def test_query_v3_not_found(
    device_client: DeviceClient,
) -> None:
    """Query with an identifier that does not exist."""
    # Use a specific ID that should not exist
    data = await device_client.query_by_id(file_id=99999999, equipment_no="SN123")

    assert data.entries_vo is None
    assert data.equipment_no == "SN123"
