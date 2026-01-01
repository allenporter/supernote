from aiohttp.test_utils import TestClient

from tests.conftest import TEST_USERNAME, UserStorageHelper


async def test_query_v3_success(
    client: TestClient,
    user_storage: UserStorageHelper,
    auth_headers: dict[str, str],
) -> None:
    # Create a test file
    user_storage.create_file(TEST_USERNAME, "Note/test.note", content="content")

    # Query by ID (relative path)
    resp = await client.post(
        "/api/file/3/files/query_v3",
        json={"equipmentNo": "SN123", "id": "Note/test.note"},
        headers=auth_headers,
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["entriesVO"]["id"] == "17171877091523463945"
    assert data["entriesVO"]["name"] == "test.note"
    assert data["entriesVO"]["path_display"] == "/Note/test.note"
    # MD5 of "content" is 9a0364b9e99bb480dd25e1f0284c8555
    assert data["entriesVO"]["content_hash"] == "9a0364b9e99bb480dd25e1f0284c8555"


async def test_query_v3_not_found(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/file/3/files/query_v3",
        json={"equipmentNo": "SN123", "id": "Note/missing.note"},
        headers=auth_headers,
    )

    assert resp.status == 200
    data = await resp.json()
    assert data == {
        "success": True,
        "equipmentNo": "SN123",
    }
