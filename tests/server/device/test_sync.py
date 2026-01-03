import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import delete

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.exceptions import UnauthorizedException
from supernote.client.login_client import LoginClient
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from tests.server.conftest import (
    TEST_PASSWORD,
    TEST_USERNAME,
    UserStorageHelper,
)


@pytest.fixture(name="login_client")
async def supernote_login_client_fixture(client: TestClient) -> LoginClient:
    base_url = str(client.make_url("/"))
    real_client = Client(client.session, host=base_url)
    return LoginClient(real_client)


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


async def test_login_flow(client: TestClient, login_client: LoginClient) -> None:
    """Test login flow."""
    login_result = await login_client.login_equipment(
        TEST_USERNAME, TEST_PASSWORD, "SN123456"
    )

    assert login_result.success
    assert len(login_result.token) > 10
    assert login_result.is_bind == "N"
    assert login_result.is_bind_equipment == "N"
    assert login_result.user_name == TEST_USERNAME

    # 5. Verify Token Works
    token = login_result.token
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


async def test_invalid_password(client: TestClient) -> None:
    """Test login with an invalid password"""
    base_url = str(client.make_url("/"))
    # Initialize client with empty host to interact with TestClient server
    real_client = Client(client.session, host=base_url)
    login_client = LoginClient(real_client)

    with pytest.raises(UnauthorizedException):
        await login_client.login_equipment(
            TEST_USERNAME, "incorrect-password", "SN123456"
        )


async def test_bind_equipment(client: TestClient) -> None:
    resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": TEST_USERNAME,
            "equipmentNo": "SN123456",
            "flag": "1",
            "name": "Supernote A6 X2 Nomad",
            "totalCapacity": "32000000",
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
    storage_root: Path,
    user_storage: UserStorageHelper,
    session_manager: DatabaseSessionManager,
) -> None:
    # Clear storage root for test
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    # Clear VFS state for this user
    async with session_manager.session() as session:
        # Delete all nodes for simplicity. In a real shared DB this would be bad,
        # but here we are in a test environment with a shared in-memory DB.
        # Ideally we filter by user_id but we need to resolve it first.
        await session.execute(delete(UserFileDO))
        await session.commit()
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
    await user_storage.create_file(TEST_USERNAME, "Note/test.note")

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

# TODO: Test upload flow with various chunk sizes and verify the server always
# receives the right content and right hash. If needed we can combine upload
# and download flow tests.abs

async def test_upload_flow(
    device_client: DeviceClient, client: TestClient, auth_headers: dict[str, str]
) -> None:
    # 1. Apply for upload
    content = b"test content"
    upload_response = await device_client.upload_content(
        path="/EXPORT/test.note",
        equipment_no="SN123456",
        content=content,
    )
    assert upload_response
    assert upload_response.content_hash == hashlib.md5(content).hexdigest()
    assert upload_response.id
    assert upload_response.size == len(content)
    assert upload_response.name == "test.note"
    # TODO: Fix invalid path_display
    assert upload_response.path_display == "//EXPORT/test.note"


async def test_download_flow(
    device_client: DeviceClient, client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Upload a file first
    file_content = b"Hello Download"
    upload_response = await device_client.upload_content(
        path="/EXPORT/download_test.note",
        content=file_content,
        equipment_no="SN123456",
    )
    assert upload_response

    # Request Download URL
    query_resp = await device_client.query_by_path(
        path="/EXPORT/download_test.note",
        equipment_no="SN123456",
    )
    assert query_resp
    assert query_resp.entries_vo
    file_id = int(query_resp.entries_vo.id)

    download_resp = await device_client.download_v3(
        file_id=file_id,
        equipment_no="SN123456",
    )
    assert download_resp
    assert download_resp.url
    download_url = download_resp.url

    # TODO: We should add a download content function in the client library that
    # handles directly fetching the content from the server.

    # Our test harness only wants relative urls so strip off the
    # hostname part and use the path and query only
    fetch_url = urlparse(download_url)
    fetch_urlstr = fetch_url.path + "?" + fetch_url.query
    resp = await client.get(fetch_urlstr, headers=auth_headers)
    assert resp.status == 200
    content = await resp.read()
    assert content == file_content
