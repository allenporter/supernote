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
from supernote.server.services.storage import StorageService

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


def test_id_generation(tmp_path: Path) -> None:
    service = StorageService(tmp_path / "storage", tmp_path / "temp")
    
    path1 = "EXPORT/test.note"
    id1 = service.get_id_from_path(path1)
    
    # Stable ID
    assert service.get_id_from_path(path1) == id1
    
    # Different ID for different path
    path2 = "EXPORT/test2.note"
    assert service.get_id_from_path(path2) != id1
    
    # Test path resolution (requires file to exist)
    (service.storage_root / "EXPORT").mkdir(parents=True, exist_ok=True)
    (service.storage_root / "EXPORT" / "test.note").touch()
    
    resolved_path = service.get_path_from_id(id1)
    assert resolved_path == path1


async def test_create_directory(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    client = await aiohttp_client(create_app())
    
    # Create folder
    resp = await client.post(
        "/api/file/2/files/create_folder_v2",
        json={  
            "equipmentNo": "SN123456",
            "path": "/NewFolder",
            "autorename": False
        },
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    
    # Verify existence
    storage_path = tmp_path / "supernote_data/storage" # Default from create_app logic if using default config...
    # Wait, create_app uses config.STORAGE_ROOT. 
    # In tests, config uses default env vars if not patched.
    # Default is os.getcwd() / "storage".
    # BUT, we are not mocking storage root in this test fixture, so it writes to current dir "storage"?
    # That's bad. 
    # However, create_app creates services with config.
    
    # Let's inspect create_app to see where it gets config.
    
    # For now, verify via list endpoint to be safe
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
    
    # 1. Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/DeleteMe"},
        headers=auth_headers,
    )
    
    # 2. Get ID via list
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    entry = next(e for e in data["entries"] if e["name"] == "DeleteMe")
    folder_id = int(entry["id"])
    
    # 3. Delete
    resp = await client.post(
        "/api/file/3/files/delete_folder_v3",
        json={"equipmentNo": "SN123456", "id": folder_id},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    
    # 4. Verify gone
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/"},
        headers=auth_headers,
    )
    data = await resp.json()
    assert not any(e["name"] == "DeleteMe" for e in data["entries"])
