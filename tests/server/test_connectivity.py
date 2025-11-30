import pytest
from unittest.mock import patch
from pathlib import Path
from typing import Callable, Awaitable
import hashlib
import aiohttp

from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.app import create_app

# Type alias for the aiohttp_client fixture
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> str:
    log_file = tmp_path / "trace.log"
    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        yield str(log_file)


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path):
    storage_root = tmp_path / "storage"
    temp_root = tmp_path / "storage" / "temp"
    storage_root.mkdir(parents=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    # Create default folders
    (storage_root / "Note").mkdir()
    (storage_root / "Document").mkdir()
    (storage_root / "EXPORT").mkdir()

    with (
        patch("supernote.server.app.STORAGE_ROOT", storage_root),
        patch("supernote.server.app.TEMP_ROOT", temp_root),
    ):
        yield


async def test_server_root(aiohttp_client: AiohttpClient, mock_trace_log: str) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Supernote Private Cloud Server" in text


async def test_trace_logging(
    aiohttp_client: AiohttpClient, mock_trace_log: str
) -> None:
    client = await aiohttp_client(create_app())
    await client.get("/some/random/path")

    log_file = Path(mock_trace_log)
    assert log_file.exists()
    content = log_file.read_text()
    assert "/some/random/path" in content
    assert "GET" in content


async def test_query_server(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.get("/api/file/query/server")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_equipment_unlink(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/terminal/equipment/unlink",
        json={"equipmentNo": "SN123456", "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_check_user_exists(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/official/user/check/exists/server",
        json={"email": "test@example.com", "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_auth_flow(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())

    # 1. CSRF
    resp = await client.get("/api/csrf")
    assert resp.status == 200
    assert "X-XSRF-TOKEN" in resp.headers

    # 2. Query Token
    resp = await client.post("/api/user/query/token")
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # 3. Random Code
    resp = await client.post(
        "/api/official/user/query/random/code", json={"account": "test@example.com"}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "randomCode" in data
    assert "timestamp" in data

    # 4. Login (Equipment)
    resp = await client.post(
        "/api/official/user/account/login/equipment",
        json={
            "account": "test@example.com",
            "password": "hashed_password",
            "timestamp": data["timestamp"],
            "equipmentNo": "SN123456",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "token" in data
    assert "userName" in data
    assert "isBind" in data


async def test_bind_equipment(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": "test@example.com",
            "equipmentNo": "SN123456",
            "flag": "1",
            "name": "Supernote A6 X2 Nomad",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_user_query(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post("/api/user/query")
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "user" in data
    assert data["user"]["userName"] == "Supernote User"


async def test_sync_start(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/file/2/files/synchronous/start", json={"equipmentNo": "SN123456"}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "synType" in data


async def test_sync_end(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123456", "flag": "N"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_list_folder(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/", "recursive": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "entries" in data
    assert len(data["entries"]) > 0
    assert data["entries"][0]["tag"] == "folder"


async def test_capacity_query(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/file/2/users/get_space_usage",
        json={"equipmentNo": "SN123456", "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "used" in data
    assert "allocationVO" in data
    assert data["allocationVO"]["allocated"] > 0


async def test_query_by_path(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post(
        "/api/file/3/files/query/by/path_v3",
        json={"equipmentNo": "SN123456", "path": "/EXPORT/test.note"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "entriesVO" in data
    assert data["entriesVO"] is None


async def test_upload_flow(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())

    # 1. Apply for upload
    resp = await client.post(
        "/api/file/3/files/upload/apply",
        json={
            "equipmentNo": "SN123456",
            "path": "/EXPORT/test.note",
            "fileName": "test.note",
            "size": "1024",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "fullUploadUrl" in data
    upload_url = data["fullUploadUrl"]

    # 2. Perform upload (using the returned URL)
    from urllib.parse import urlparse

    parsed_url = urlparse(upload_url)
    upload_path = parsed_url.path

    # Use multipart upload
    from aiohttp import FormData

    data = FormData()
    data.add_field("file", b"test content", filename="test.note")

    resp = await client.post(upload_path, data=data)
    assert resp.status == 200

    # 3. Finish upload
    content = b"test content"
    content_hash = hashlib.md5(content).hexdigest()

    resp = await client.post(
        "/api/file/2/files/upload/finish",
        json={
            "equipmentNo": "SN123456",
            "fileName": "test.note",
            "path": "/EXPORT/",
            "content_hash": content_hash,
            "size": len(content),
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True


async def test_download_flow(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())

    # 1. Upload a file first
    file_content = b"Hello Download"
    file_hash = hashlib.md5(file_content).hexdigest()

    # Apply
    await client.post(
        "/api/file/3/files/upload/apply",
        json={
            "equipmentNo": "SN123456",
            "fileName": "download_test.note",
            "fileMd5": file_hash,
            "size": len(file_content),
            "path": "/EXPORT/",
        },
    )

    # Upload Data
    data = aiohttp.FormData()
    data.add_field("file", file_content, filename="download_test.note")
    await client.post("/api/file/upload/data/download_test.note", data=data)

    # Finish
    await client.post(
        "/api/file/2/files/upload/finish",
        json={
            "equipmentNo": "SN123456",
            "fileName": "download_test.note",
            "path": "/EXPORT/",
            "content_hash": file_hash,
            "size": len(file_content),
        },
    )

    # 2. Request Download
    resp = await client.post(
        "/api/file/3/files/download_v3",
        json={"equipmentNo": "SN123456", "id": "EXPORT/download_test.note"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    download_url = data["url"]
    assert "path=EXPORT/download_test.note" in download_url

    # 3. Download Data
    # Extract path from URL
    path_param = download_url.split("path=")[1]
    resp = await client.get(f"/api/file/download/data?path={path_param}")
    assert resp.status == 200
    content = await resp.read()
    assert content == file_content
