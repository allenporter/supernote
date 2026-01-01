from pathlib import Path

from supernote.server.app import create_app
from supernote.server.services.storage import StorageService
from tests.conftest import AiohttpClient


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


async def test_create_directory(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    client = await aiohttp_client(create_app())

    # Create folder
    resp = await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/NewFolder", "autorename": False},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Verify folder exists
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert any(e["name"] == "NewFolder" for e in data["entries"])


async def test_delete_folder(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

    # Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/DeleteMe"},
        headers=auth_headers,
    )

    # Get ID via list
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "DeleteMe")
    folder_id = int(entry["id"])

    # Delete
    resp = await client.post(
        "/api/file/3/files/delete_folder_v3",
        json={"equipmentNo": "SN123456", "id": folder_id},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Verify gone
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert not any(e["name"] == "DeleteMe" for e in data["entries"])


async def test_list_recursive(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

    # Create /Parent
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Parent"},
        headers=auth_headers,
    )

    # Create /Parent/Child
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Parent/Child"},
        headers=auth_headers,
    )

    # List non-recursive from root
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/", "recursive": False},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()

    results = sorted((e["name"], e["path_display"]) for e in data["entries"])
    assert results == [
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]

    # List recursive from root
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/", "recursive": True},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()

    results = sorted((e["name"], e["path_display"]) for e in data["entries"])
    assert results == [
        ("Child", "/Parent/Child"),
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]
