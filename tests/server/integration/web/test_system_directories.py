import pytest

from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient


async def test_web_cannot_delete_system_directories(web_client: WebClient) -> None:
    """Verify that system directories cannot be deleted via Web API."""
    # List root to get IDs
    res = await web_client.list_query(directory_id=0)
    assert res.success

    # Find Note folder
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")
    note_id = int(note_folder.id)

    # Attempt to delete
    with pytest.raises(ApiException, match="Cannot delete system directory"):
        await web_client.file_delete(id_list=[note_id], parent_id=0)

    # Verify still exists
    res_after = await web_client.list_query(directory_id=0)
    assert any(f.file_name == "Note" for f in res_after.user_file_vo_list)


async def test_device_cannot_delete_system_directories(
    device_client: DeviceClient,
) -> None:
    """Verify that system directories cannot be deleted via Device API."""
    # Device sees NOTE container
    res = await device_client.list_folder("/", recursive=False)
    note_container = next(e for e in res.entries if e.name == "NOTE")
    note_container_id = int(note_container.id)

    # Attempt to delete by ID (Device API uses delete_folder_v3 via .delete())
    with pytest.raises(ApiException, match="Cannot delete system directory"):
        await device_client.delete(id=note_container_id, equipment_no="TEST")

    # Verify still exists
    res_after = await device_client.list_folder("/", recursive=False)
    assert any(e.name == "NOTE" for e in res_after.entries)


async def test_device_cannot_delete_flattened_folders(
    device_client: DeviceClient,
) -> None:
    """Verify that device cannot delete Note even if it knows the ID."""
    # 1. Find NOTE's ID
    res = await device_client.list_folder("/", recursive=False)
    note_container = next(e for e in res.entries if e.name == "NOTE")

    # 2. Find Note folder INSIDE NOTE
    children_res = await device_client.list_folder(folder_id=int(note_container.id))
    note_folder = next(e for e in children_res.entries if e.name == "Note")
    note_id = int(note_folder.id)

    # 3. Attempt to delete
    with pytest.raises(ApiException, match="Cannot delete system directory"):
        await device_client.delete(id=note_id, equipment_no="TEST")
