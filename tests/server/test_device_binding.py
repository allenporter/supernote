import hashlib
from typing import Any

from aiohttp.test_utils import TestClient

from tests.conftest import TEST_PASSWORD, TEST_USERNAME


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


async def test_device_binding_lifecycle(client: TestClient) -> None:
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


async def test_user_profile_persistence(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Query Profile
    resp = await client.post("/api/user/query", headers=auth_headers, json={})
    # Note: user/query uses header token, doesn't strictly need body if using middleware correctly?
    # but the handler does `account = request.get("user")` which comes from middleware.

    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Check default profile name from fixture
    assert data["user"]["userName"] == "Test User"
