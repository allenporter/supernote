import hashlib
from pathlib import Path

import jwt
import pytest
from aiohttp import FormData

from supernote.client import Client
from supernote.server.config import AuthConfig, ServerConfig, UserEntry
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import JWT_ALGORITHM
from tests.server.conftest import TEST_PASSWORD

USER_A = "user_a@example.com"
USER_B = "user_b@example.com"


@pytest.fixture
def mock_storage() -> None:
    """Mock storage for tests."""
    pass


@pytest.fixture
def server_config(storage_root: Path, mock_trace_log: str) -> ServerConfig:
    """Create a test config with multiple users."""
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
        storage_dir=str(storage_root),
        auth=AuthConfig(
            users=users,
            secret_key="test-secret-key",
        ),
    )


async def register_session(
    coordination_service: CoordinationService, user: str, secret: str
) -> dict[str, str]:
    """Register a session for a user."""
    token = jwt.encode({"sub": user}, secret, algorithm=JWT_ALGORITHM)
    session_val = f"{user}|"
    await coordination_service.set_value(f"session:{token}", session_val, ttl=3600)
    return {"x-access-token": token}


async def test_multi_user_clobber(
    client: Client,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    headers_a = await register_session(
        coordination_service, USER_A, server_config.auth.secret_key
    )
    headers_b = await register_session(
        coordination_service, USER_B, server_config.auth.secret_key
    )

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

    # User A list files should see their file
    resp = await client.post(
        "/api/file/2/files/list_folder",
        json={"path": "/", "equipmentNo": "EQ001"},
        headers=headers_a,
    )
    assert resp.status == 200
    data = await resp.json()
    assert [e["name"] for e in data["entries"]] == ["shared.note"]

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
    assert data["success"]
    assert data.get("entriesVO")
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
    assert data["success"]
    assert data.get("entriesVO")
    assert data["entriesVO"]["content_hash"] == hash_b, (
        "User B should have their own file content"
    )
