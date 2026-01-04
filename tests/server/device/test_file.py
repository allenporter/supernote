from supernote.client.device import DeviceClient


async def test_delete_file(device_client: DeviceClient) -> None:
    """Test deleting a file."""
    await device_client.create_folder(path="MyFolder", equipment_no="SN123456")

    upload_result = await device_client.upload_content(
        path="MyFolder/MyFile.txt",
        content=b"Hello World",
        equipment_no="SN123456",
    )
    assert upload_result
    assert upload_result.id
    assert upload_result.name == "MyFile.txt"
    assert upload_result.size == 11
    assert upload_result.path_display == "MyFolder/MyFile.txt"

    # Verify file exists
    data = await device_client.list_folder(path="MyFolder", equipment_no="SN123456")
    assert data.entries
    assert len(data.entries) == 1
    assert data.entries[0].name == "MyFile.txt"
    assert data.entries[0].id == upload_result.id
    assert data.entries[0].tag == "file"
    assert data.entries[0].path_display == "MyFolder/MyFile.txt"
    assert data.entries[0].size == 11

    # Delete file
    delete_result = await device_client.delete(
        id=int(upload_result.id), equipment_no="SN123456"
    )
    assert delete_result.equipment_no == "SN123456"
    assert delete_result.metadata
    assert delete_result.metadata.id == upload_result.id
    assert delete_result.metadata.name == "MyFile.txt"
    assert delete_result.metadata.tag == "file"
    assert delete_result.metadata.path_display == "MyFolder/MyFile.txt"

    # Verify gone
    data = await device_client.list_folder(path="MyFolder", equipment_no="SN123456")
    assert not data.entries
