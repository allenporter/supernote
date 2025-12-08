"""Tests for file search functionality."""

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


async def test_search_by_filename(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test searching for files by filename."""
    client = await aiohttp_client(create_app())

    # Create some test folders and files
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Documents"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes/Meeting"},
        headers=auth_headers,
    )

    # Search for "Notes"
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "Notes"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "Notes"
    assert data["entries"][0]["tag"] == "folder"


async def test_search_case_insensitive(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test that search is case-insensitive."""
    client = await aiohttp_client(create_app())

    # Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/MyFolder"},
        headers=auth_headers,
    )

    # Search with lowercase
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "myfolder"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "MyFolder"


async def test_search_partial_match(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test that search matches partial filenames."""
    client = await aiohttp_client(create_app())

    # Create folders
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Meeting2024"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Meeting2023"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )

    # Search for "Meeting"
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "Meeting"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data["entries"]) == 2
    names = {entry["name"] for entry in data["entries"]}
    assert names == {"Meeting2024", "Meeting2023"}


async def test_search_no_results(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test search with no matching results."""
    client = await aiohttp_client(create_app())

    # Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )

    # Search for non-existent keyword
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "NonExistent"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert len(data["entries"]) == 0
