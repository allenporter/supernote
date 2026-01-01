from aiohttp.test_utils import TestClient


async def test_soft_delete_to_recycle(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Create a folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/TestFolder"},
        headers=auth_headers,
    )

    # Get ID of folder
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "TestFolder")
    item_id = int(entry["id"])

    # Delete (soft delete to recycle bin)
    resp = await client.post(
        "/api/file/3/files/delete_folder_v3",
        json={"equipmentNo": "SN123456", "id": item_id},
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify not in main folder
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert not any(e["name"] == "TestFolder" for e in data["entries"])

    # Verify in recycle bin
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 1
    assert data["recycleFileVOList"][0]["fileName"] == "TestFolder"
    assert data["recycleFileVOList"][0]["isFolder"] == "Y"


async def test_recycle_revert(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Create and delete a folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/ToRestore"},
        headers=auth_headers,
    )

    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "ToRestore")
    item_id = int(entry["id"])

    await client.post(
        "/api/file/3/files/delete_folder_v3",
        json={"equipmentNo": "SN123456", "id": item_id},
        headers=auth_headers,
    )

    # Get recycle bin item ID
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    recycle_id = int(data["recycleFileVOList"][0]["fileId"])

    # Revert from recycle bin
    resp = await client.post(
        "/api/file/recycle/revert",
        json={"idList": [recycle_id]},
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify back in main folder
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert any(e["name"] == "ToRestore" for e in data["entries"])

    # Verify not in recycle bin
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    assert data["total"] == 0


async def test_recycle_permanent_delete(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Create and delete a folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/ToDelete"},
        headers=auth_headers,
    )

    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "ToDelete")
    item_id = int(entry["id"])

    await client.post(
        "/api/file/3/files/delete_folder_v3",
        json={"equipmentNo": "SN123456", "id": item_id},
        headers=auth_headers,
    )

    # Get recycle bin item ID
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    recycle_id = int(data["recycleFileVOList"][0]["fileId"])

    # Permanently delete from recycle bin
    resp = await client.post(
        "/api/file/recycle/delete",
        json={"idList": [recycle_id]},
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify not in recycle bin
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    assert data["total"] == 0


async def test_recycle_clear(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Default folders
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert len(data["entries"]) == 3

    # Create and delete multiple folders
    for name in ["Folder1", "Folder2", "Folder3"]:
        await client.post(
            "/api/file/2/files/create_folder_v2",
            json={"equipmentNo": "SN123456", "path": f"/{name}"},
            headers=auth_headers,
        )

    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert len(data["entries"]) == 6

    for entry in data["entries"]:
        await client.post(
            "/api/file/3/files/delete_folder_v3",
            json={"equipmentNo": "SN123456", "id": int(entry["id"])},
            headers=auth_headers,
        )

    # Verify 6 items in recycle bin
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    assert data["total"] == 6

    # Clear recycle bin
    resp = await client.post(
        "/api/file/recycle/clear",
        json={},
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify recycle bin is empty
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    assert data["total"] == 0
