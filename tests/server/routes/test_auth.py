import hashlib
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.admin import AdminClient
from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import ApiException, UnauthorizedException
from supernote.client.login_client import LoginClient
from supernote.client.web import WebClient
from supernote.models.equipment import UserEquipmentVO
from supernote.models.user import UserCheckVO, UserRegisterDTO
from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SupernoteError
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService
from supernote.server.utils.rate_limit import LIMIT_LOGIN_IP_MAX, LIMIT_PW_RESET_MAX


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


async def test_equipment_unlink(login_client: LoginClient) -> None:
    with pytest.raises(ApiException, match="Invalid request format"):
        await login_client.unlink_equipment("")

    res = await login_client.unlink_equipment("EQ123")
    assert res.success is True


async def test_check_user_exists(
    login_client: LoginClient,
    user_service: UserService,
    create_test_user: None,
) -> None:
    with pytest.raises(ApiException, match="Invalid request format"):
        await login_client.check_user_exists("")

    user_id = await user_service.get_user_id("test@example.com")
    res = await login_client.check_user_exists("test@example.com")
    assert isinstance(res.unique_machine_id, str) and len(res.unique_machine_id) > 0
    assert res == UserCheckVO(
        user_id=user_id,
        unique_machine_id=res.unique_machine_id,
        dms="ALL",
    )

    with pytest.raises(ApiException, match="User not found"):
        await login_client.check_user_exists("unknown@example.com")


async def test_login_invalid_credentials(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    # Wrong password on existing user returns HTTP 200 with E0019 (Password error)
    code_resp = await client.post(
        "/api/official/user/query/random/code",
        json={"account": "test@example.com"},
    )
    code_data = await code_resp.json()
    wrong_pw_resp = await client.post(
        "/api/official/user/account/login/new",
        json={
            "account": "test@example.com",
            "password": "invalid_sha256_hash",
            "timestamp": code_data["timestamp"],
            "loginMethod": "2",
        },
    )
    assert wrong_pw_resp.status == 200
    assert await wrong_pw_resp.json() == {
        "success": False,
        "errorCode": "E0019",
        "errorMsg": "Password error",
        "token": "",
        "counts": "1",
        "isBind": "N",
        "isBindEquipment": "N",
        "soldOutCount": 0,
    }

    # Non-existent user returns HTTP 200 with E0018 (Account does not exist)
    unknown_resp = await client.post(
        "/api/official/user/account/login/new",
        json={
            "account": "nonexistent@example.com",
            "password": "invalid_sha256_hash",
            "timestamp": "1234567890",
            "loginMethod": "2",
        },
    )
    assert unknown_resp.status == 200
    assert await unknown_resp.json() == {
        "success": False,
        "errorCode": "E0018",
        "errorMsg": "Account does not exist",
        "token": "",
        "counts": "0",
        "isBind": "N",
        "isBindEquipment": "N",
        "soldOutCount": 0,
    }

    with pytest.raises(UnauthorizedException, match="Password error"):
        await login_client.login("test@example.com", "wrongpassword")

    with pytest.raises(UnauthorizedException, match="Account does not exist"):
        await login_client.login("nonexistent@example.com", "wrongpassword")


async def test_bind_equipment(
    client: TestClient,
    login_client: LoginClient,
    user_service: UserService,
    create_test_user: None,
) -> None:
    resp = await client.post("/api/terminal/user/bindEquipment", json={})
    assert resp.status == 400
    data = await resp.json()
    assert data["errorMsg"] == "Missing data"

    for path in (
        "/api/equipment/query/by/equipmentno",
        "/api/official/equipment/query/by/equipmentno",
    ):
        bad_resp = await client.post(path, json={})
        assert bad_resp.status == 400
        assert (await bad_resp.json())["errorMsg"] == "Invalid request format"

        empty_resp = await client.post(path, json={"equipmentNo": ""})
        assert empty_resp.status == 400
        assert (await empty_resp.json())["errorMsg"] == "Invalid request format"

        unbound_resp = await client.post(path, json={"equipmentNo": "EQ123"})
        assert unbound_resp.status == 200
        assert await unbound_resp.json() == {
            "success": True,
        }

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

    user_id = await user_service.get_user_id("test@example.com")
    for path in (
        "/api/equipment/query/by/equipmentno",
        "/api/official/equipment/query/by/equipmentno",
    ):
        bound_resp = await client.post(path, json={"equipmentNo": "EQ123"})
        assert bound_resp.status == 200
        assert await bound_resp.json() == {
            "success": True,
            "equipmentNumber": "EQ123",
            "userId": user_id,
            "status": "Y",
        }

    assert await login_client.query_equipment_by_no("EQ123") == UserEquipmentVO(
        equipment_number="EQ123",
        user_id=user_id,
        status="Y",
    )

    # Re-binding to the same user succeeds idempotently
    same_user_resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": "test@example.com",
            "equipmentNo": "EQ123",
            "name": "Device",
            "totalCapacity": "1000",
        },
    )
    assert same_user_resp.status == 200
    assert (await same_user_resp.json())["success"] is True

    # Binding to a different user while already bound is rejected
    await user_service.register(
        UserRegisterDTO(
            email="other@example.com",
            password=hashlib.md5(b"password").hexdigest(),
        )
    )
    other_user_resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={
            "account": "other@example.com",
            "equipmentNo": "EQ123",
            "name": "Device",
            "totalCapacity": "1000",
        },
    )
    assert other_user_resp.status == 400
    other_data = await other_user_resp.json()
    assert other_data["success"] is False
    assert "already bound" in other_data["errorMsg"]


async def test_user_query(
    client: TestClient,
    web_client: WebClient,
) -> None:
    base_url = str(client.make_url(""))
    unauth_client = Client(client.session, host=base_url)
    unauth_web = WebClient(unauth_client)
    with pytest.raises(ApiException):
        await unauth_web.query_user()

    res = await web_client.query_user()
    assert res.success is True
    assert res.user_name == "Test User"
    assert res.total_capacity is not None
    assert int(res.total_capacity) > 0


async def test_user_register_errors_and_success(
    client: TestClient,
    admin_client: AdminClient,
    user_service: UserService,
    create_test_user: None,
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
            user_service,
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
        patch.object(user_service, "register", side_effect=Exception("Crash")),
        pytest.raises(ApiException),
    ):
        await admin_client.register(
            email="newreg@example.com", password=pwd_hash, username="Reg User"
        )

    # Success
    await admin_client.register(
        email="newreg@example.com", password=pwd_hash, username="Reg User"
    )


class SimpleTokenAuth(AbstractAuth):
    def __init__(self, token: str):
        self.token = token

    async def async_get_access_token(self) -> str:
        return self.token


async def test_user_account_clear(
    client: TestClient,
    web_client: WebClient,
    admin_client: AdminClient,
    login_client: LoginClient,
    user_service: UserService,
    server_config: ServerConfig,
) -> None:
    """Test user account clear lifecycle and verify user ID / file isolation."""
    unauth_clear = await client.post("/api/user/account/clear", json={})
    assert unauth_clear.status == 401

    user1_id = await user_service.get_user_id("test@example.com")

    # User 1 creates a folder and uploads a file
    folder = await web_client.create_folder(parent_id=0, name="User1PrivateFolder")
    folder_id = int(folder.id)
    await web_client.upload_file(
        parent_id=folder_id, name="secret.txt", content=b"user1 secret"
    )

    res1 = await web_client.list_query(directory_id=folder_id)
    assert len(res1.user_file_vo_list) == 1
    assert res1.user_file_vo_list[0].file_name == "secret.txt"

    # Disabling registration causes account/clear to fail with 400
    server_config.auth.enable_registration = False
    with pytest.raises(ApiException):
        await admin_client.clear_account(confirm=True)
    server_config.auth.enable_registration = True

    # User 1 deletes their account
    await admin_client.clear_account(confirm=True)

    # User 2 registers
    base_url = str(client.make_url(""))
    unauth_client = Client(client.session, host=base_url)
    unauth_admin = AdminClient(unauth_client)

    pwd = "password123"
    pwd_md5 = hashlib.md5(pwd.encode("utf-8")).hexdigest()
    await unauth_admin.register("user2@example.com", pwd_md5, "User 2")

    user2_id = await user_service.get_user_id("user2@example.com")

    # User 2 logs in
    user2_token = await login_client.login("user2@example.com", pwd)
    user2_authed_client = Client(
        client.session, auth=SimpleTokenAuth(user2_token), host=base_url
    )
    user2_web = WebClient(user2_authed_client)

    root_listing = await user2_web.list_query(directory_id=0)
    folder_names = [f.file_name for f in root_listing.user_file_vo_list]

    res2 = await user2_web.list_query(directory_id=folder_id)
    user2_files = [f.file_name for f in res2.user_file_vo_list]

    assert user1_id != user2_id
    assert "User1PrivateFolder" not in folder_names
    assert len(user2_files) == 0


async def test_update_password_and_email(
    client: TestClient,
    admin_client: AdminClient,
    login_client: LoginClient,
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

    # Invalid password format (not MD5) -> 400
    with pytest.raises(ApiException):
        await admin_client.update_password("not-an-md5-hash")

    # Invalid email format -> 400
    with pytest.raises(ApiException):
        await admin_client.update_email("not-an-email")

    # Malformed DTOs on auth endpoints -> 400
    for path in (
        "/api/official/user/query/random/code",
        "/api/official/user/account/login/new",
    ):
        resp = await client.post(path, json={})
        assert resp.status == 400

    # Update password succeeds and revokes old session
    pwd_hash = hashlib.md5(b"newpassword").hexdigest()
    await admin_client.update_password(pwd_hash)

    with pytest.raises(ApiException):
        await admin_client.update_email("new@example.com")

    # Re-login with new password and update email
    new_token = await login_client.login("test@example.com", "newpassword")
    authed_client = Client(
        client.session, auth=SimpleTokenAuth(new_token), host=base_url
    )
    reauthed_admin = AdminClient(authed_client)
    await reauthed_admin.update_email("new@example.com")

    # Old token for test@example.com is now revoked
    with pytest.raises(ApiException):
        await reauthed_admin.update_email("another@example.com")


async def test_email_change_prevents_old_token_principal_confusion(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Ensure changing email revokes old tokens and prevents re-registered email takeover."""
    base_url = str(client.make_url(""))
    victim_old_token = await login_client.login("test@example.com", "testpassword")
    victim_client = Client(
        client.session, auth=SimpleTokenAuth(victim_old_token), host=base_url
    )
    victim_admin = AdminClient(victim_client)

    # Victim changes email to victim_new@example.com
    await victim_admin.update_email("victim_new@example.com")

    # Attacker registers the freed test@example.com address
    unauth_client = Client(client.session, host=base_url)
    unauth_admin = AdminClient(unauth_client)
    attacker_pw = hashlib.md5(b"attackerpw").hexdigest()
    await unauth_admin.register("test@example.com", attacker_pw, "Attacker")

    # Victim's pre-change token MUST NOT authenticate as Attacker
    resp = await client.post(
        "/api/user/query",
        headers={"x-access-token": victim_old_token},
        json={},
    )
    assert resp.status == 401


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


async def test_login_rate_limit(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    # Setup
    account = "limit@example.com"
    pwd_hash = hashlib.md5(b"password").hexdigest()

    # URL
    url = "/api/official/user/account/login/new"

    # Use mocked time to prevent flaky tests crossing time/bucket boundaries
    with patch(
        "supernote.server.utils.rate_limit.time.time", return_value=1600000000.0
    ):
        # 1. First N attempts should succeed
        # The rate limiter is checked BEFORE login logic.
        for i in range(LIMIT_LOGIN_IP_MAX):
            # Use unique account to avoid hitting account limit (which is lower than IP limit)
            # We want to test IP limit here.
            unique_account = f"limit{i}@example.com"
            resp = await client.post(
                url,
                json={
                    "account": unique_account,
                    "password": pwd_hash,
                    "equipmentNo": "TEST",
                    "timestamp": "1234567890",
                    "loginMethod": "1",
                },
            )
            if resp.status == 500:
                text = await resp.text()
                pytest.fail(f"Login failed with 500 on attempt {i + 1}: {text}")

            assert resp.status in [
                200,
                401,
            ]  # 401 because user might not exist, but NOT 429

        # LIMIT + 1 attempt should be 429
        resp = await client.post(
            url,
            json={
                "account": account,
                "password": pwd_hash,
                "equipmentNo": "TEST",
                "timestamp": "1234567890",
                "loginMethod": "1",
            },
        )
        assert resp.status == 429
        data = await resp.json()
        assert "Rate limit exceeded" in data["errorMsg"]


async def test_password_retrieve_rate_limit(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    # Enable remote password reset for this test
    # client.app is the aiohttp Application
    server_config.auth.enable_remote_password_reset = True

    # Setup
    account = "limit_reset@example.com"
    pwd_hash = hashlib.md5(b"password").hexdigest()

    # URL
    url = "/api/official/user/retrieve/password"

    # Use mocked time to prevent flaky tests crossing time/bucket boundaries
    with patch(
        "supernote.server.utils.rate_limit.time.time", return_value=1600000000.0
    ):
        # Limit is 5 per hour
        for i in range(LIMIT_PW_RESET_MAX):
            resp = await client.post(url, json={"email": account, "password": pwd_hash})
            if resp.status == 500:
                text = await resp.text()
                pytest.fail(f"Reset failed with 500 on attempt {i + 1}: {text}")
            assert resp.status in [200, 404]  # 404/200 OK

        # 6th attempt -> 429
        resp = await client.post(url, json={"email": account, "password": pwd_hash})
        assert resp.status == 429


async def test_public_auth_endpoints_share_ip_rate_limit(
    client: TestClient,
) -> None:
    pwd_hash = hashlib.md5(b"password").hexdigest()
    with patch(
        "supernote.server.utils.rate_limit.time.time", return_value=1600000000.0
    ):
        for i in range(LIMIT_LOGIN_IP_MAX):
            resp = await client.post(
                "/api/official/user/query/random/code",
                json={"account": f"user{i}@example.com"},
            )
            assert resp.status == 200

        # Subsequent calls to public auth endpoints from the same IP are rate-limited (429)
        for url, payload in (
            (
                "/api/official/user/query/random/code",
                {"account": "extra@example.com"},
            ),
            (
                "/api/official/user/check/exists/server",
                {"email": "extra@example.com"},
            ),
            (
                "/api/terminal/equipment/unlink",
                {"equipmentNo": "EQ123"},
            ),
            (
                "/api/terminal/user/bindEquipment",
                {
                    "account": "extra@example.com",
                    "equipmentNo": "EQ123",
                    "name": "Device",
                    "totalCapacity": "1000",
                },
            ),
            (
                "/api/equipment/query/by/equipmentno",
                {"equipmentNo": "EQ123"},
            ),
            (
                "/api/user/register",
                {
                    "email": "extra@example.com",
                    "password": pwd_hash,
                    "userName": "Extra",
                },
            ),
        ):
            resp = await client.post(url, json=payload)
            assert resp.status == 429


async def test_user_query_routes_and_equipment_no(
    client: TestClient,
    auth_headers: dict[str, str],
    create_test_user: None,
) -> None:
    """Test /api/user/query and /api/user/query/info routes with auth and DTO parameters."""
    # Unauthenticated requests return 401
    resp = await client.post("/api/user/query", json={})
    assert resp.status == 401
    data = await resp.json()
    assert data["success"] is False

    resp = await client.post("/api/user/query/info", json={})
    assert resp.status == 401
    data = await resp.json()
    assert data["success"] is False

    # Authenticated user query
    resp = await client.post("/api/user/query", headers=auth_headers, json={})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["email"] == "test@example.com"

    # Authenticated user query info with DTO equipmentNo
    resp = await client.post(
        "/api/user/query/info",
        headers=auth_headers,
        json={"equipmentNo": "EQUIP_999"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["equipmentNo"] == "EQUIP_999"
    assert data["user"]["email"] == "test@example.com"


async def test_logout_and_account_clear(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Test POST /api/user/logout single-session revocation and POST /api/user/account/clear."""
    # Unauthenticated logout returns 401
    unauth_resp = await client.post("/api/user/logout", json={})
    assert unauth_resp.status == 401

    base_url = str(client.make_url(""))
    token_a = await login_client.login("test@example.com", "testpassword")
    token_b = await login_client.login("test@example.com", "testpassword")

    client_a = Client(client.session, auth=SimpleTokenAuth(token_a), host=base_url)
    login_a = LoginClient(client_a)
    web_a = WebClient(client_a)

    client_b = Client(client.session, auth=SimpleTokenAuth(token_b), host=base_url)
    web_b = WebClient(client_b)

    # Log out session A via LoginClient.logout()
    await login_a.logout()

    # Session A is revoked, Session B remains active
    with pytest.raises(ApiException):
        await web_a.query_user()

    res_b = await web_b.query_user()
    assert res_b.success is True

    # POST /api/user/account/clear deletes account and revokes remaining sessions
    clear_resp = await client.post(
        "/api/user/account/clear",
        headers={"x-access-token": token_b},
        json={},
    )
    assert clear_resp.status == 200
    assert (await clear_resp.json())["success"] is True

    with pytest.raises(ApiException):
        await web_b.query_user()
