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
    return {"x-access-token": token}


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


async def test_move_file(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

    # 1. Create file via upload (mocked flow or just assume pre-existence logic via helper)
    # Actually, let's create a folder first to move things into
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/SourceFolder"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/DestFolder"},
        headers=auth_headers,
    )

    # Create subfolder to move
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/SourceFolder/ToMove"},
        headers=auth_headers,
    )

    # Get ID of /SourceFolder/ToMove
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/SourceFolder"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "ToMove")
    item_id = int(entry["id"])

    # Move /SourceFolder/ToMove -> /DestFolder/ToMove
    resp = await client.post(
        "/api/file/3/files/move_v3",
        json={
            "equipmentNo": "SN123456",
            "id": item_id,
            "to_path": "/DestFolder",
            "autorename": False,
        },
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Verify in DestFolder
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/DestFolder"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert any(e["name"] == "ToMove" for e in data["entries"])

    # Verify NOT in SourceFolder
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/SourceFolder"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert not any(e["name"] == "ToMove" for e in data["entries"])


async def test_copy_file_autorename(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

    # Create Folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/CopySource"},
        headers=auth_headers,
    )

    # Create Item
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/CopySource/Item"},
        headers=auth_headers,
    )

    # Get ID
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/CopySource"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "Item")
    item_id = int(entry["id"])

    # Copy to same folder (requires autorename)
    resp = await client.post(
        "/api/file/3/files/copy_v3",
        json={
            "equipmentNo": "SN123456",
            "id": item_id,
            "to_path": "/CopySource",
            "autorename": True,
        },
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify both exist
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/CopySource"},
        headers=auth_headers,
    )
    data = await resp.json()
    names = [e["name"] for e in data["entries"]]
    assert "Item" in names
    # Should find Item(1) or similar. Since "Item" has no extension, it's just Item(1)
    assert any(n.startswith("Item(1)") for n in names)
