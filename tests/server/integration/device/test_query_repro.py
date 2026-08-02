from supernote.client.device import DeviceClient


async def test_repro_sync_failure_with_category_path(
    device_client: DeviceClient,
) -> None:
    """Reproduction for Sync Failure due to category path."""
    # 1. Setup: Create 'Document/Archive' folder by uploading a file
    content = b"test content"
    upload_result = await device_client.upload_content(
        "DOCUMENT/Document/Archive/test.doc", content, equipment_no="SN123"
    )
    assert upload_result.equipment_no == "SN123"
    assert upload_result.id
    assert upload_result.name == "test.doc"
    assert upload_result.path_display == "DOCUMENT/Document/Archive/test.doc"
    assert upload_result.size == len(content)

    # 2. Query with capitalized category prefix: DOCUMENT/Document/Archive
    # This currently fails with 404 because get_file_info doesn't flatten the path
    path = "DOCUMENT/Document/Archive"

    # We expect this to SUCCEED to query the parent folder.
    resp = await device_client.query_by_path(path=path, equipment_no="SN123")
    assert resp.entries_vo
    assert resp.entries_vo.name == "Archive"
    assert resp.entries_vo.path_display == "DOCUMENT/Document/Archive"
    assert resp.entries_vo.id != upload_result.id

    # Query the uploaded file
    resp = await device_client.query_by_path(
        path="DOCUMENT/Document/Archive/test.doc", equipment_no="SN123"
    )
    assert resp.entries_vo
    assert resp.entries_vo.id == upload_result.id
    assert resp.entries_vo.name == "test.doc"
    assert resp.entries_vo.path_display == "DOCUMENT/Document/Archive/test.doc"
