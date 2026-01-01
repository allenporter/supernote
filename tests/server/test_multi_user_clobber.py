import hashlib
from pathlib import Path

import jwt
import pytest
from aiohttp import FormData

from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig, UserEntry
from supernote.server.services.user import JWT_ALGORITHM
from tests.conftest import TEST_PASSWORD, AiohttpClient

USER_A = "user_a@example.com"
USER_B = "user_b@example.com"


@pytest.fixture
def multi_user_config(mock_storage: Path, mock_trace_log: str) -> ServerConfig:
    users = [
        UserEntry(
            username=USER_A,
            password_md5=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
            is_active=True,
            display_name="User A",
        ),
        UserEntry(
            username=USER_B,
            password_md5=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
            is_active=True,
            display_name="User B",
        ),
    ]

    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(mock_storage),
        auth=AuthConfig(
            users=users,
            secret_key="test-secret-key",
        ),
    )


async def register_session(app, user: str, secret: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = jwt.encode({"sub": user}, secret, algorithm=JWT_ALGORITHM)
    app["state_service"].create_session(token, user)

    # Also seed CoordinationService
    session_val = f"{user}|"
    await app["coordination_service"].set_value(
        f"session:{token}", session_val, ttl=3600
    )

    return {"x-access-token": token}


async def test_multi_user_clobber(
    aiohttp_client: AiohttpClient, multi_user_config: ServerConfig
) -> None:
    app = create_app(multi_user_config)
    client = await aiohttp_client(app)

    headers_a = await register_session(app, USER_A, multi_user_config.auth.secret_key)
    headers_b = await register_session(app, USER_B, multi_user_config.auth.secret_key)

    # 1. User A uploads a file
    filename = "shared.note"
    content_a = b"User A content"
    hash_a = hashlib.md5(content_a).hexdigest()

    # Upload data for User A
    data_a = FormData()
    data_a.add_field("file", content_a, filename=filename)
    resp = await client.post(
        f"/api/file/upload/data/{filename}", data=data_a, headers=headers_a
    )
    assert resp.status == 200

    # Finish upload for User A
    resp = await client.post(
        "/api/file/2/files/upload/finish",
        json={
            "equipmentNo": "EQ001",
            "fileName": filename,
            "path": "/",
            "content_hash": hash_a,
        },
        headers=headers_a,
    )
    assert resp.status == 200

    # 2. User B list files - SHOULD NOT see User A's file
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"path": "/", "equipmentNo": "EQ002"},
        headers=headers_b,
    )
    assert resp.status == 200
    data = await resp.json()
    assert not any(e["name"] == filename for e in data["entries"]), (
        "User B should not see User A's file"
    )

    # 3. User B uploads a file with the same name
    content_b = b"Content from User B"
    hash_b = hashlib.md5(content_b).hexdigest()

    form_b = FormData()
    form_b.add_field("file", content_b, filename=filename)
    resp = await client.post(
        f"/api/file/upload/data/{filename}", data=form_b, headers=headers_b
    )
    assert resp.status == 200

    resp = await client.post(
        "/api/file/2/files/upload/finish",
        json={
            "equipmentNo": "EQ002",
            "fileName": filename,
            "path": "/",
            "content_hash": hash_b,
        },
        headers=headers_b,
    )
    assert resp.status == 200

    # 4. User A queries their file - SHOULD STILL HAVE THEIR CONTENT
    resp = await client.post(
        "/api/file/3/files/query/by/path_v3",
        json={"path": f"/{filename}", "equipmentNo": "EQ001"},
        headers=headers_a,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["entriesVO"]["content_hash"] == hash_a, (
        "User A's file should NOT be clobbered by User B"
    )

    # 5. User B queries their file - SHOULD HAVE THEIR CONTENT
    resp = await client.post(
        "/api/file/3/files/query/by/path_v3",
        json={"path": f"/{filename}", "equipmentNo": "EQ002"},
        headers=headers_b,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["entriesVO"]["content_hash"] == hash_b, (
        "User B should have their own file content"
    )
