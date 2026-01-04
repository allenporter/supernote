from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.exceptions import UnauthorizedException
from supernote.client.login_client import LoginClient
from tests.server.conftest import TEST_PASSWORD, TEST_USERNAME


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


async def test_check_user_exists(create_test_user: None, client: TestClient) -> None:
    resp = await client.post(
        "/api/official/user/check/exists/server",
        json={"email": TEST_USERNAME, "version": "202407"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_login_flow(
    create_test_user: None, client: TestClient, login_client: LoginClient
) -> None:
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
