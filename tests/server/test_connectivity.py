import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiohttp import FormData
from aiohttp.test_utils import TestClient

from supernote.server.services.storage import StorageService
from tests.conftest import (
    TEST_PASSWORD,
    TEST_USERNAME,
    UserStorageHelper,
)


def _sha256_s(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _md5_s(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _encode_password(password: str, rc: str) -> str:
    return _sha256_s(_md5_s(password) + rc)


async def test_trace_logging(client: TestClient, mock_trace_log: str) -> None:
    await client.get("/some/random/path")

    log_file = Path(mock_trace_log)
    assert log_file.exists()
    content = log_file.read_text()
    assert "/some/random/path" in content
    assert "GET" in content


async def test_query_server(client: TestClient) -> None:
    resp = await client.get("/api/file/query/server")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_equipment_unlink(client: TestClient) -> None:
    resp = await client.post(
        "/api/terminal/equipment/unlink",
        json={"equipmentNo": "SN123456", "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_check_user_exists(client: TestClient) -> None:
    resp = await client.post(
        "/api/official/user/check/exists/server",
        json={"email": TEST_USERNAME, "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_auth_flow(client: TestClient) -> None:
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
        "/api/official/user/query/random/code", json={"account": TEST_USERNAME}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    code = data["randomCode"]
    assert "timestamp" in data
    timestamp = data["timestamp"]

    # 4. Login (Equipment)
    # Verify an incorrect password is not allowed
    resp = await client.post(
        "/api/official/user/account/login/equipment",
        json={
            "account": TEST_USERNAME,
            "password": "foo",
            "timestamp": timestamp,
            "equipmentNo": "SN123456",
        },
    )
    assert resp.status == 401
    data = await resp.json()
    assert data == {"success": False, "errorMsg": "Invalid credentials"}

    # Try a correct password
    password = _encode_password(TEST_PASSWORD, code)
    resp = await client.post(
        "/api/official/user/account/login/equipment",
        json={
            "account": TEST_USERNAME,
            "password": password,
            "timestamp": timestamp,
            "equipmentNo": "SN123456",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert "token" in data
    data_token = data["token"]
    del data["token"]
    assert data == {
        "isBind": "N",
        "isBindEquipment": "N",
        "soldOutCount": 0,
        "success": True,
        "userName": TEST_USERNAME,
    }

    # 5. Verify Token Works
    token = data_token
    resp = await client.post("/api/user/query", headers={"x-access-token": token})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["user"]["userName"] == "Test User"
    assert data["equipmentNo"] == "SN123456"

    # Verify an invalid token does not work
    resp = await client.post(
        "/api/user/query", headers={"x-access-token": "invalid_token"}
    )
    assert resp.status == 401
    data = await resp.json()
    assert data["success"] is False
    assert data["errorMsg"] == "Invalid token"
    assert "equipmentNo" not in data


async def test_bind_equipment(client: TestClient) -> None:
    resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": TEST_USERNAME,
            "equipmentNo": "SN123456",
            "flag": "1",
            "name": "Supernote A6 X2 Nomad",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_user_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post("/api/user/query", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "user" in data
    assert data["user"]["userName"] == "Test User"


async def test_sync_start_syn_type(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_service: StorageService,
    user_storage: UserStorageHelper,
) -> None:
    # Clear storage root for test
    if storage_service.root_dir.exists():
        shutil.rmtree(str(storage_service.root_dir))
    storage_service._ensure_directories()

    # 1. Initially storage is empty, should return synType: False
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is False  # Empty storage

    # 2. Add a dummy file
    user_storage.create_file(TEST_USERNAME, "Note/test.note")

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is True  # Non-empty storage


async def test_sync_lock(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 1. Start sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 2. Try sync from SN456 (same user), should get 409
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 409
    data = await resp.json()
    assert data["errorCode"] == "E0078"

    # 3. End sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123", "flag": "true"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 4. Now SN456 should be able to sync
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    assert (await resp.json())["success"] is True


async def test_list_folder(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"equipmentNo": "SN123456", "path": "/", "recursive": False},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "entries" in data
    assert len(data["entries"]) > 0
    assert data["entries"][0]["tag"] == "folder"


async def test_capacity_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/file/2/users/get_space_usage",
        json={"equipmentNo": "SN123456", "version": "202407"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "used" in data
    assert "allocationVO" in data
    assert data["allocationVO"]["allocated"] > 0


async def test_query_by_path(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/file/3/files/query/by/path_v3",
        json={"equipmentNo": "SN123456", "path": "/EXPORT/test.note"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    # entriesVO is omitted if None (file not found)
    assert "entriesVO" not in data


async def test_upload_flow(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 1. Apply for upload
    resp = await client.post(
        "/api/file/3/files/upload/apply",
        json={
            "equipmentNo": "SN123456",
            "path": "/EXPORT/test.note",
            "fileName": "test.note",
            "size": "1024",
        },
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "fullUploadUrl" in data
    upload_url = data["fullUploadUrl"]

    # 2. Perform upload (using the returned URL)
    parsed_url = urlparse(upload_url)
    upload_path = parsed_url.path

    # Use multipart upload
    data = FormData()
    data.add_field("file", b"test content", filename="test.note")

    resp = await client.post(upload_path, data=data, headers=auth_headers)
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
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True


async def test_download_flow(client: TestClient, auth_headers: dict[str, str]) -> None:
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
    await client.post(
        "/api/file/upload/data/download_test.note", data=data, headers=auth_headers
    )

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
        headers=auth_headers,
    )

    # 2. Request Download
    resp = await client.post(
        "/api/file/3/files/download_v3",
        json={"equipmentNo": "SN123456", "id": "EXPORT/download_test.note"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    download_url = data["url"]
    assert "path=EXPORT/download_test.note" in download_url

    # 3. Download Data
    # Extract path from URL
    path_param = download_url.split("path=")[1]
    resp = await client.get(
        f"/api/file/download/data?path={path_param}", headers=auth_headers
    )
    assert resp.status == 200
    content = await resp.read()
    assert content == file_content
