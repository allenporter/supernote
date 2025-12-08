import hashlib
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import jwt
import pytest
import yaml
from aiohttp.test_utils import TestClient

from supernote.server.app import create_app
from supernote.server.services.user import JWT_ALGORITHM, JWT_SECRET

from .fixtures import TEST_PASSWORD, TEST_USERNAME, AiohttpClient


@pytest.fixture
def mock_users_file(tmp_path: Path) -> Generator[str, None, None]:
    user = {
        "username": TEST_USERNAME,
        "password_md5": hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
        "is_active": True,
        # Initially empty devices
        "devices": [],
        "profile": {"user_name": "Test User"},
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


@pytest.fixture(autouse=True)
def patch_server_config(
    mock_trace_log: str, mock_users_file: str
) -> Generator[None, None, None]:
    with (
        patch("supernote.server.config.TRACE_LOG_FILE", mock_trace_log),
        patch("supernote.server.config.USER_CONFIG_FILE", mock_users_file),
    ):
        yield


def _get_auth_header(client: TestClient) -> dict[str, str]:
    # We can't generate a token easily without login because we need dynamic secrets
    # So we'll rely on the login flow or use a helper if we exposed the secret
    # But actually, the tests usually mock the secret or use the one from user.py
    token = jwt.encode({"sub": TEST_USERNAME}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"x-access-token": token}


async def _login(client: TestClient, equipment_no: str) -> Any:
    # 1. Get Random Code
    resp = await client.post(
        "/api/official/user/query/random/code", json={"account": TEST_USERNAME}
    )
    data = await resp.json()
    code = data["randomCode"]
    timestamp = data["timestamp"]

    # 2. Login
    pwd_md5 = hashlib.md5(TEST_PASSWORD.encode()).hexdigest()
    concat = pwd_md5 + code
    password_hash = hashlib.sha256(concat.encode()).hexdigest()

    resp = await client.post(
        "/api/official/user/account/login/equipment",
        json={
            "account": TEST_USERNAME,
            "password": password_hash,
            "timestamp": timestamp,
            "equipmentNo": equipment_no,
        },
    )
    return await resp.json()


async def test_device_binding_lifecycle(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    equipment_a = "SN-A"

    # 1. Login WITHOUT binding
    data = await _login(client, equipment_a)
    assert data["success"] is True
    # Should not be bound yet
    assert data["isBind"] == "N"
    assert data["isBindEquipment"] == "N"

    # 2. Bind the device
    resp = await client.post(
        "/api/terminal/user/bindEquipment",
        json={"account": TEST_USERNAME, "equipmentNo": equipment_a},
    )
    assert resp.status == 200
    assert (await resp.json())["success"] is True

    # 3. Login AGAIN (verify binding)
    data = await _login(client, equipment_a)
    assert data["success"] is True
    assert data["isBind"] == "Y"
    assert data["isBindEquipment"] == "Y"

    # 4. Login with DIFFERENT device (verify partial binding)
    equipment_b = "SN-B"
    data = await _login(client, equipment_b)
    # User is bound (to A), but THIS device (B) is not bound
    assert data["isBind"] == "Y"
    assert data["isBindEquipment"] == "N"

    # 5. Unlink Device A
    resp = await client.post(
        "/api/terminal/equipment/unlink", json={"equipmentNo": equipment_a}
    )
    assert resp.status == 200

    # 6. Login with Device A again (verify unbind)
    data = await _login(client, equipment_a)
    # Now user has NO devices bound (if A was the only one)
    assert data["isBind"] == "N"  # Assuming list is empty now
    assert data["isBindEquipment"] == "N"


async def test_user_profile_persistence(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())

    # Authenticate
    headers = _get_auth_header(client)

    # Query Profile
    resp = await client.post("/api/user/query", headers=headers, json={})
    # Note: user/query uses header token, doesn't strictly need body if using middleware correctly?
    # but the handler does `account = request.get("user")` which comes from middleware.

    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Check default profile name from fixture
    assert data["user"]["userName"] == "Test User"
