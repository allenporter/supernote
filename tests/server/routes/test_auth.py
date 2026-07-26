import hashlib
from unittest.mock import patch

import jwt
import pytest
from aiohttp.test_utils import TestClient

from supernote.client.admin import AdminClient
from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import ApiException, UnauthorizedException
from supernote.client.login_client import LoginClient
from supernote.client.web import WebClient
from supernote.server.config import ServerConfig
from supernote.server.exceptions import SupernoteError


async def test_empty_token(
    client: Client,
) -> None:
    result = await client.post("/api/user/query/token")
    data = await result.json()
    assert data == {
        "success": True,
        "token": None,
        "errorCode": None,
        "errorMsg": None,
    }


async def test_equipment_unlink(client: TestClient) -> None:
    resp = await client.post("/api/terminal/equipment/unlink", json={})
    assert resp.status == 400
    data = await resp.json()
    assert data["errorMsg"] == "Invalid request format"

    resp = await client.post(
        "/api/terminal/equipment/unlink", json={"equipmentNo": "EQ123"}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True


async def test_check_user_exists(client: TestClient, create_test_user: None) -> None:
    resp = await client.post(
        "/api/official/user/check/exists/server", json={"email": "test@example.com"}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    resp = await client.post(
        "/api/official/user/check/exists/server",
        json={"email": "unknown@example.com"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is False
    assert data["errorMsg"] == "User not found"


async def test_login_invalid_credentials(login_client: LoginClient) -> None:
    with pytest.raises(UnauthorizedException):
        await login_client.login("test@example.com", "wrongpassword")


async def test_bind_equipment(client: TestClient, create_test_user: None) -> None:
    resp = await client.post("/api/terminal/user/bindEquipment", json={})
    assert resp.status == 400
    data = await resp.json()
    assert data["errorMsg"] == "Missing data"

    resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": "test@example.com",
            "equipmentNo": "EQ123",
            "name": "Device",
            "totalCapacity": "1000",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True


async def test_user_query(
    client: TestClient,
    web_client: WebClient,
) -> None:
    base_url = str(client.make_url(""))
    unauth_client = Client(client.session, host=base_url)
    unauth_web = WebClient(unauth_client)
    with pytest.raises(ApiException):
        await unauth_web.query_user()

    secret = client.app["config"].auth.secret_key
    bad_token = jwt.encode(
        {"sub": "nonexistent@example.com"}, secret, algorithm="HS256"
    )
    await client.app["coordination_service"].set_value(
        f"session:{bad_token}", "nonexistent@example.com|", ttl=3600
    )

    class BadAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return bad_token

    bad_client = Client(client.session, auth=BadAuth(), host=base_url)
    bad_web = WebClient(bad_client)
    with pytest.raises(ApiException):
        await bad_web.query_user()

    res = await web_client.query_user()
    assert res.user is not None
    assert res.user.user_name == "Test User"


async def test_user_register_errors_and_success(
    client: TestClient, admin_client: AdminClient, create_test_user: None
) -> None:
    resp = await client.post("/api/user/register", json={})
    assert resp.status == 400

    pwd_hash = hashlib.md5(b"pwd").hexdigest()

    # ValueError in register (existing user)
    with pytest.raises(ApiException):
        await admin_client.register(
            email="test@example.com", password=pwd_hash, username="Dup User"
        )

    # SupernoteError in register
    with (
        patch.object(
            client.app["user_service"],
            "register",
            side_effect=SupernoteError("Reg error", status_code=400),
        ),
        pytest.raises(ApiException),
    ):
        await admin_client.register(
            email="newreg@example.com", password=pwd_hash, username="Reg User"
        )

    # Uncaught Exception
    with (
        patch.object(
            client.app["user_service"], "register", side_effect=Exception("Crash")
        ),
        pytest.raises(ApiException),
    ):
        await admin_client.register(
            email="newreg@example.com", password=pwd_hash, username="Reg User"
        )

    # Success
    await admin_client.register(
        email="newreg@example.com", password=pwd_hash, username="Reg User"
    )


async def test_user_unregister(
    admin_client: AdminClient,
) -> None:
    await admin_client.unregister()


async def test_update_password_and_email(
    client: TestClient,
    admin_client: AdminClient,
) -> None:
    base_url = str(client.make_url(""))
    unauth_client = Client(client.session, host=base_url)
    unauth_admin = AdminClient(unauth_client)

    # Password: Unauthorized
    with pytest.raises(ApiException):
        await unauth_admin.update_password("newpassword")

    # Email: Unauthorized
    with pytest.raises(ApiException):
        await unauth_admin.update_email("new@example.com")

    # Success paths
    pwd_hash = hashlib.md5(b"newpassword").hexdigest()
    await admin_client.update_password(pwd_hash)
    await admin_client.update_email("new@example.com")


async def test_retrieve_password_paths(
    client: TestClient, server_config: ServerConfig, create_test_user: None
) -> None:
    base_url = str(client.make_url(""))
    supernote_client = Client(client.session, host=base_url)
    admin_client = AdminClient(supernote_client)

    pwd_hash = hashlib.md5(b"password").hexdigest()

    # Remote password reset disabled -> 403
    server_config.auth.enable_remote_password_reset = False
    with pytest.raises(ApiException):
        await admin_client.retrieve_password("test@example.com", pwd_hash)

    server_config.auth.enable_remote_password_reset = True

    # User not found -> 404
    with pytest.raises(ApiException):
        await admin_client.retrieve_password("notfound@example.com", pwd_hash)

    # Success -> 200
    await admin_client.retrieve_password("test@example.com", pwd_hash)


async def test_query_login_record(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/user/query/loginRecord", json={})
    assert resp.status == 401

    resp = await client.post(
        "/api/user/query/loginRecord",
        json={"pageNo": 2, "pageSize": 10},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert "data" in data
    assert data["total"] == 0
