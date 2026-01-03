from supernote.client.device import DeviceClient
from supernote.models.file import EntriesVO


async def test_device_list_folder(device_client: DeviceClient) -> None:
    # 1. Create directory structure
    # Root
    #  - FolderDevice
    #    - FileDevice

    await device_client.create_folder(path="/FolderDevice", equipment_no="test")
    await device_client.upload_content("/FolderDevice/FileDevice.txt", b"content_device")

    # 2. List Root (V2 API usually, allows path)
    res_root = await device_client.list_folder(path="/", equipment_no="test")
    assert any(e.name == "FolderDevice" for e in res_root.entries)

    # 3. List Subfolder
    # Device API V2/V3 often can list by path or ID.
    # list_folder client method usually uses V2 endpoint which takes path.
    res_sub = await device_client.list_folder(path="/FolderDevice", equipment_no="test")
    assert len(res_sub.entries) == 1
    assert res_sub.entries[0].name == "FileDevice.txt"
