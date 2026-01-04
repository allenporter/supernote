import pytest

from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException


@pytest.mark.parametrize(
    "path", ["NewFolder", "/NewFolder", "/NewFolder/", "NewFolder/"]
)
async def test_create_directory(device_client: DeviceClient, path: str) -> None:
    """Create a directory and verify it exists with various path formats."""
    result = await device_client.create_folder(path=path, equipment_no="SN123456")
    assert result.equipment_no == "SN123456"
    assert result.metadata
    assert result.metadata.id
    assert result.metadata.name == "NewFolder"
    assert result.metadata.tag == "folder"
    assert result.metadata.path_display == "NewFolder"

    # Verify folder exists
    data = await device_client.list_folder(path="", equipment_no="SN123456")
    assert any(e.name == "NewFolder" for e in data.entries)


async def test_delete_folder(device_client: DeviceClient) -> None:
    """Test deleting a folder."""
    create_result = await device_client.create_folder(
        path="DeleteMe", equipment_no="SN123456"
    )
    assert create_result.equipment_no == "SN123456"
    assert create_result.metadata
    assert create_result.metadata.id
    assert create_result.metadata.name == "DeleteMe"
    assert create_result.metadata.tag == "folder"
    assert create_result.metadata.path_display == "DeleteMe"
    folder_id = int(create_result.metadata.id)

    # Verify folder exists
    # Get ID via list
    data = await device_client.list_folder(path="", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "DeleteMe")
    assert folder_id == int(entry.id)

    # Delete
    delete_result = await device_client.delete(id=folder_id, equipment_no="SN123456")
    assert delete_result.equipment_no == "SN123456"
    assert delete_result.metadata
    assert int(delete_result.metadata.id) == folder_id
    assert delete_result.metadata.name == "DeleteMe"
    assert delete_result.metadata.tag == "folder"
    assert delete_result.metadata.path_display == "DeleteMe"

    # Verify gone
    data = await device_client.list_folder(path="", equipment_no="SN123456")
    assert not any(e.name == "DeleteMe" for e in data.entries)


async def test_list_recursive(device_client: DeviceClient) -> None:
    """Test listing folders recursively."""
    # Create /Parent
    await device_client.create_folder(path="Parent", equipment_no="SN123456")

    # Create /Parent/Child
    await device_client.create_folder(path="Parent/Child", equipment_no="SN123456")

    # List non-recursive from root
    data = await device_client.list_folder(
        path="/", equipment_no="SN123456", recursive=False
    )

    # TODO: This is not testing parent path and needs to be updated.
    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("DOCUMENT", "DOCUMENT"),
        ("Export", "Export"),
        ("Inbox", "Inbox"),
        ("NOTE", "NOTE"),
        ("Parent", "Parent"),
        ("Screenshot", "Screenshot"),
    ]

    # List recursive from root
    data = await device_client.list_folder(
        path="/", equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Child", "Parent/Child"),
        ("DOCUMENT", "DOCUMENT"),
        ("Document", "DOCUMENT/Document"),
        ("Export", "Export"),
        ("Inbox", "Inbox"),
        ("MyStyle", "NOTE/MyStyle"),
        ("NOTE", "NOTE"),
        ("Note", "NOTE/Note"),
        ("Parent", "Parent"),
        ("Screenshot", "Screenshot"),
    ]


async def test_list_subdirectory(device_client: DeviceClient) -> None:
    """Test listing folders in a subdirectory."""
    # Create /FolderA/FolderB
    result = await device_client.create_folder(path="/FolderA", equipment_no="SN123456")
    assert result.equipment_no == "SN123456"
    assert result.metadata
    assert result.metadata.id
    assert result.metadata.name == "FolderA"
    assert result.metadata.tag == "folder"
    assert result.metadata.path_display == "FolderA"

    result = await device_client.create_folder(
        path="/FolderA/FolderB", equipment_no="SN123456"
    )
    assert result.equipment_no == "SN123456"
    assert result.metadata
    assert result.metadata.id
    assert result.metadata.name == "FolderB"
    assert result.metadata.tag == "folder"
    assert result.metadata.path_display == "FolderA/FolderB"

    # Get ID of FolderA
    data = await device_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "FolderA")
    folder_a_id = int(entry.id)

    # List recursive from FolderA
    data = await device_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)

    # Expect FolderB. Path display should be full path /FolderA/FolderB
    assert results == [
        ("FolderB", "FolderA/FolderB", "FolderA"),
    ]

    # List flat from FolderA
    data = await device_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)
    assert results == [
        ("FolderB", "FolderA/FolderB", "FolderA"),
    ]


async def test_delete_subdirectory(device_client: DeviceClient) -> None:
    """Test deleting a subdirectory."""
    # Create FolderA/FolderB
    result_root = await device_client.create_folder(
        path="FolderA", equipment_no="SN123456"
    )
    assert result_root
    assert result_root.metadata
    assert result_root.metadata.id
    assert result_root.metadata.name == "FolderA"

    result_subfolder = await device_client.create_folder(
        path="FolderA/FolderB", equipment_no="SN123456"
    )
    assert result_subfolder
    assert result_subfolder.metadata
    assert result_subfolder.metadata.id
    assert result_subfolder.metadata.name == "FolderB"

    # Delete FolderA
    result_delete = await device_client.delete(
        id=int(result_root.metadata.id), equipment_no="SN123456"
    )
    assert result_delete
    assert result_delete.metadata
    assert result_delete.metadata.id == result_root.metadata.id
    assert result_delete.metadata.name == "FolderA"
    assert result_delete.metadata.tag == "folder"
    assert result_delete.metadata.path_display == "FolderA"

    # List recursive from root
    data = await device_client.list_folder(
        path="/", equipment_no="SN123456", recursive=True
    )
    assert not any(e.name == "FolderA" for e in data.entries)


async def test_delete_folder_does_not_exist(device_client: DeviceClient) -> None:
    """Test deleting a folder that does not exist."""
    with pytest.raises(ApiException, match="Node 123456 not found"):
        await device_client.delete(id=123456, equipment_no="SN123456")
