import hashlib
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.models.user import UserVO
from supernote.server.config import ServerConfig
from supernote.server.exceptions import SupernoteError


async def test_empty_token(
    client: Client,
) -> None:
    result = await client.post("/api/user/query/token")
    data = await result.json()
    assert data == {
        "success": True,
        "token": None,  # Client expects this field always to be present
        "errorCode": None,
        "errorMsg": None,
    }


async def test_equipment_unlink(client: TestClient) -> None:
    # 1. Invalid payload -> 400
    resp = await client.post("/api/terminal/equipment/unlink", json={})
    assert resp.status == 400
    data = await resp.json()
    assert data["errorMsg"] == "Invalid request format"

    # 2. Success
    with patch.object(
        client.app["user_service"], "unlink_equipment", new_callable=AsyncMock
    ):
        resp = await client.post(
            "/api/terminal/equipment/unlink", json={"equipmentNo": "EQ123"}
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True


async def test_check_user_exists(client: TestClient) -> None:
    # 1. User exists
    with patch.object(
        client.app["user_service"], "check_user_exists", return_value=True
    ):
        resp = await client.post(
            "/api/official/user/check/exists/server", json={"email": "test@example.com"}
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True

    # 2. User does not exist
    with patch.object(
        client.app["user_service"], "check_user_exists", return_value=False
    ):
        resp = await client.post(
            "/api/official/user/check/exists/server",
            json={"email": "unknown@example.com"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is False
        assert data["errorMsg"] == "User not found"


async def test_login_invalid_credentials(client: TestClient) -> None:
    with patch.object(client.app["user_service"], "login", return_value=None):
        resp = await client.post(
            "/api/official/user/account/login/new",
            json={
                "account": "user@example.com",
                "password": "hash",
                "equipmentNo": "EQ",
                "timestamp": "12345",
                "loginMethod": "2",
            },
        )
        assert resp.status == 401
        data = await resp.json()
        assert data["errorMsg"] == "Invalid credentials"


async def test_bind_equipment(client: TestClient) -> None:
    # Invalid DTO -> 400
    resp = await client.post("/api/terminal/user/bindEquipment", json={})
    assert resp.status == 400
    data = await resp.json()
    assert data["errorMsg"] == "Missing data"

    # Success
    with patch.object(
        client.app["user_service"], "bind_equipment", new_callable=AsyncMock
    ):
        resp = await client.post(
            "/api/terminal/user/bindEquipment",
            json={
                "account": "user@example.com",
                "equipmentNo": "EQ123",
                "name": "Device",
                "totalCapacity": "1000",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True


async def test_user_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 1. Unauthorized (no auth headers)
    resp = await client.post("/api/user/query", json={})
    assert resp.status == 401

    # 2. User not found
    with patch.object(
        client.app["user_service"], "get_user_profile", return_value=None
    ):
        resp = await client.post("/api/user/query", json={}, headers=auth_headers)
        assert resp.status == 404

    # 3. Success
    mock_profile = UserVO(user_id="1", email="test@example.com", user_name="Test User")
    with patch.object(
        client.app["user_service"], "get_user_profile", return_value=mock_profile
    ):
        resp = await client.post("/api/user/query", json={}, headers=auth_headers)
        assert resp.status == 200


async def test_user_register_errors_and_success(client: TestClient) -> None:
    # 1. Invalid DTO format -> 400
    resp = await client.post("/api/user/register", json={})
    assert resp.status == 400

    payload = {"email": "reg@example.com", "password": "pwd", "userName": "Reg User"}

    # 2. ValueError in register -> 400
    with patch.object(
        client.app["user_service"],
        "register",
        side_effect=ValueError("Email already in use"),
    ):
        resp = await client.post("/api/user/register", json=payload)
        assert resp.status == 400

    # 3. SupernoteError in register -> status_code
    with patch.object(
        client.app["user_service"],
        "register",
        side_effect=SupernoteError("Reg error", status_code=400),
    ):
        resp = await client.post("/api/user/register", json=payload)
        assert resp.status == 400

    # 4. Uncaught Exception -> 500
    with patch.object(
        client.app["user_service"], "register", side_effect=Exception("Crash")
    ):
        resp = await client.post("/api/user/register", json=payload)
        assert resp.status == 500

    # 5. Success -> 200
    with patch.object(client.app["user_service"], "register", new_callable=AsyncMock):
        resp = await client.post("/api/user/register", json=payload)
        assert resp.status == 200


async def test_user_unregister(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # 1. Unauthorized
    resp = await client.post("/api/user/unregister", json={})
    assert resp.status == 401

    # 2. Success
    with patch.object(client.app["user_service"], "unregister", new_callable=AsyncMock):
        resp = await client.post("/api/user/unregister", json={}, headers=auth_headers)
        assert resp.status == 200


async def test_update_password_and_email(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Password: Unauthorized
    resp = await client.put("/api/user/password", json={"password": "new"})
    assert resp.status == 401

    # Password: Success
    with patch.object(
        client.app["user_service"], "update_password", new_callable=AsyncMock
    ):
        resp = await client.put(
            "/api/user/password", json={"password": "new"}, headers=auth_headers
        )
        assert resp.status == 200

    # Email: Unauthorized
    resp = await client.put("/api/user/email", json={"email": "new@example.com"})
    assert resp.status == 401

    # Email: Success
    with patch.object(
        client.app["user_service"], "update_email", new_callable=AsyncMock
    ):
        resp = await client.put(
            "/api/user/email", json={"email": "new@example.com"}, headers=auth_headers
        )
        assert resp.status == 200


async def test_retrieve_password_paths(
    client: TestClient, server_config: ServerConfig
) -> None:
    pwd_hash = hashlib.md5(b"password").hexdigest()
    url = "/api/official/user/retrieve/password"

    # 1. Remote password reset disabled -> 403
    server_config.auth.enable_remote_password_reset = False
    resp = await client.post(
        url, json={"email": "test@example.com", "password": pwd_hash}
    )
    assert resp.status == 403
    data = await resp.json()
    assert data["errorMsg"] == "Remote password reset is disabled"

    # Enable for remaining checks
    server_config.auth.enable_remote_password_reset = True

    # 2. User not found -> 404
    with patch.object(
        client.app["user_service"], "retrieve_password", return_value=False
    ):
        resp = await client.post(
            url, json={"email": "notfound@example.com", "password": pwd_hash}
        )
        assert resp.status == 404
        data = await resp.json()
        assert data["errorMsg"] == "User not found"

    # 3. Success -> 200
    with patch.object(
        client.app["user_service"], "retrieve_password", return_value=True
    ):
        resp = await client.post(
            url, json={"email": "test@example.com", "password": pwd_hash}
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True


async def test_query_login_record(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # 1. Unauthorized
    resp = await client.post("/api/user/query/loginRecord", json={})
    assert resp.status == 401

    # 2. Success with pagination
    with patch.object(
        client.app["user_service"], "query_login_records", return_value=([], 0)
    ):
        resp = await client.post(
            "/api/user/query/loginRecord",
            json={"pageNo": 2, "pageSize": 10},
            headers=auth_headers,
        )
        assert resp.status == 200
        data = await resp.json()
        assert "data" in data
        assert data["total"] == 0
