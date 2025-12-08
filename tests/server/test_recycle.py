import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Awaitable, Callable
from unittest.mock import patch

import jwt
import pytest
import yaml
from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.app import create_app
from supernote.server.services.user import JWT_ALGORITHM, JWT_SECRET

# Type alias for the aiohttp_client fixture
AiohttpClient = Callable[[Application], Awaitable[TestClient]]

TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpassword"


@pytest.fixture
def mock_users_file(tmp_path: Path) -> Generator[str, None, None]:
    user = {
        "username": TEST_USERNAME,
        "password_md5": hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
        "is_active": True,
    }
    users_file = tmp_path / "users.yaml"
    with open(users_file, "w") as f:
        yaml.safe_dump({"users": [user]}, f)
    yield str(users_file)


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> Generator[str, None, None]:
    log_file = tmp_path / "trace.log"
    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        yield str(log_file)


@pytest.fixture(name="auth_headers")
def auth_headers_fixture() -> dict[str, str]:
    # Generate a fake JWT token for test@example.com
    token = jwt.encode({"sub": TEST_USERNAME}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def patch_server_config(
    mock_trace_log: str, mock_users_file: str, tmp_path: Path
) -> Generator[None, None, None]:
    storage_dir = tmp_path / "storage_test"
    with (
        patch("supernote.server.config.TRACE_LOG_FILE", mock_trace_log),
        patch("supernote.server.config.USER_CONFIG_FILE", mock_users_file),
        patch("supernote.server.config.STORAGE_DIR", str(storage_dir)),
    ):
        yield


async def test_soft_delete_to_recycle(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

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


async def test_recycle_revert(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

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
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

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


async def test_recycle_clear(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

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

    for entry in data["entries"]:
        await client.post(
            "/api/file/3/files/delete_folder_v3",
            json={"equipmentNo": "SN123456", "id": int(entry["id"])},
            headers=auth_headers,
        )

    # Verify 3 items in recycle bin
    resp = await client.post(
        "/api/file/recycle/list/query",
        json={"order": "time", "sequence": "desc", "pageNo": 1, "pageSize": 20},
        headers=auth_headers,
    )
    data = await resp.json()
    assert data["total"] == 3

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
