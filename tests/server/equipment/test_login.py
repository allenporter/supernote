import asyncio
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.exceptions import UnauthorizedException
from supernote.client.login_client import LoginClient
from tests.server.conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> str:
    """Enable trace log for this module."""
    log_file = tmp_path / "trace.log"
    return str(log_file)


async def test_trace_logging(client: TestClient, mock_trace_log: str) -> None:
    await client.get("/some/random/path")

    log_file = Path(mock_trace_log)
    # Wait for the async file write thread to finish writing and flushing
    content = ""
    for _ in range(20):
        if log_file.exists():
            content = log_file.read_text()
            if "/some/random/path" in content:
                break
        await asyncio.sleep(0.05)

    assert log_file.exists()
    assert "/some/random/path" in content
    assert "GET" in content


async def test_query_server(client: TestClient) -> None:
    resp = await client.get("/api/file/query/server")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_equipment_unlink(login_client: LoginClient) -> None:
    res = await login_client.unlink_equipment(equipment_no="SN123456")
    assert res.success


async def test_check_user_exists(
    create_test_user: None, login_client: LoginClient
) -> None:
    res = await login_client.check_user_exists(email=TEST_USERNAME)
    assert res.success


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


async def test_invalid_password(login_client: LoginClient) -> None:
    """Test login with an invalid password"""
    with pytest.raises(UnauthorizedException):
        await login_client.login_equipment(
            TEST_USERNAME, "incorrect-password", "SN123456"
        )


async def test_bind_equipment(login_client: LoginClient) -> None:
    res = await login_client.bind_equipment(
        account=TEST_USERNAME,
        equipment_no="SN123456",
        name="Supernote A6 X2 Nomad",
        total_capacity="32000000",
        flag="1",
    )
    assert res.success


async def test_user_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post("/api/user/query", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "user" in data
    assert data["user"]["userName"] == "Test User"
