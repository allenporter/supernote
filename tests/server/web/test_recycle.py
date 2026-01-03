from supernote.client.device import DeviceClient
from supernote.client.web import WebClient


async def test_soft_delete_to_recycle(
    web_client: WebClient,
    device_client: DeviceClient,
    auth_headers: dict[str, str],
) -> None:
    # Create a folder
    await device_client.create_folder(path="/TestFolder", equipment_no="SN123456")

    # Get ID of folder
    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    entry = next(e for e in list_folder_result.entries if e.name == "TestFolder")
    item_id = int(entry.id)

    # Delete (soft delete to recycle bin)
    await device_client.delete(id=item_id, equipment_no="SN123456")

    # Verify not in main folder
    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    assert not any(e.name == "TestFolder" for e in list_folder_result.entries)

    # Verify in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 1
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    assert recycle_list_result.recycle_file_vo_list[0].file_name == "TestFolder"
    assert recycle_list_result.recycle_file_vo_list[0].is_folder == "Y"


async def test_recycle_revert(
    web_client: WebClient,
    device_client: DeviceClient,
    auth_headers: dict[str, str],
) -> None:
    # Create and delete a folder
    await device_client.create_folder(path="/ToRestore", equipment_no="SN123456")

    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    entry = next(e for e in list_folder_result.entries if e.name == "ToRestore")
    item_id = int(entry.id)

    await device_client.delete(id=item_id, equipment_no="SN123456")

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Revert from recycle bin
    await web_client.recycle_revert(id_list=[recycle_id])

    # Verify back in main folder
    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    assert any(e.name == "ToRestore" for e in list_folder_result.entries)

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result.total == 0


async def test_recycle_permanent_delete(
    web_client: WebClient,
    device_client: DeviceClient,
    auth_headers: dict[str, str],
) -> None:
    # Create and delete a folder
    await device_client.create_folder(path="/ToDelete", equipment_no="SN123456")

    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    entry = next(e for e in list_folder_result.entries if e.name == "ToDelete")
    item_id = int(entry.id)

    await device_client.delete(id=item_id, equipment_no="SN123456")

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Permanently delete from recycle bin
    await web_client.recycle_delete(id_list=[recycle_id])

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0


async def test_recycle_clear(
    web_client: WebClient,
    device_client: DeviceClient,
    auth_headers: dict[str, str],
) -> None:
    # Default folders
    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    assert list_folder_result
    assert len(list_folder_result.entries) == 3

    # Create and delete multiple folders
    for name in ["Folder1", "Folder2", "Folder3"]:
        await device_client.create_folder(path=f"/{name}", equipment_no="SN123456")

    list_folder_result = await device_client.list_folder(
        path="/", equipment_no="SN123456"
    )
    assert list_folder_result
    assert len(list_folder_result.entries) == 6

    for entry in list_folder_result.entries:
        await device_client.delete(id=int(entry.id), equipment_no="SN123456")

    # Verify 6 items in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 6

    # Clear recycle bin
    await web_client.recycle_clear()

    # Verify recycle bin is empty
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0
