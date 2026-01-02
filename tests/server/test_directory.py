from pathlib import Path

from supernote.client.file import FileClient
from supernote.server.services.storage import StorageService


def test_id_generation(tmp_path: Path) -> None:
    service = StorageService(tmp_path / "storage")
    user = "testuser"

    path1 = "EXPORT/test.note"
    id1 = service.get_id_from_path(path1)

    # Stable ID
    assert service.get_id_from_path(path1) == id1

    # Different ID for different path
    path2 = "EXPORT/test2.note"
    assert service.get_id_from_path(path2) != id1

    # Test path resolution (requires file to exist)
    (service.users_dir / user / "EXPORT").mkdir(parents=True, exist_ok=True)
    (service.users_dir / user / "EXPORT" / "test.note").touch()

    resolved_path = service.get_path_from_id(user, id1)
    assert resolved_path == path1


async def test_create_directory(file_client: FileClient) -> None:
    # Create folder
    await file_client.create_folder(path="/NewFolder", equipment_no="SN123456")

    # Verify folder exists
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    assert any(e.name == "NewFolder" for e in data.entries)


async def test_delete_folder(file_client: FileClient) -> None:
    # Create folder
    await file_client.create_folder(path="/DeleteMe", equipment_no="SN123456")

    # Get ID via list
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "DeleteMe")
    folder_id = int(entry.id)

    # Delete
    await file_client.delete_folder(folder_id=folder_id, equipment_no="SN123456")

    # Verify gone
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    assert not any(e.name == "DeleteMe" for e in data.entries)


async def test_list_recursive(file_client: FileClient) -> None:
    # Create /Parent
    await file_client.create_folder(path="/Parent", equipment_no="SN123456")

    # Create /Parent/Child
    await file_client.create_folder(path="/Parent/Child", equipment_no="SN123456")

    # List non-recursive from root
    data = await file_client.list_folder(
        path="/", equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]

    # List recursive from root
    data = await file_client.list_folder(
        path="/", equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Child", "/Parent/Child"),
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]
