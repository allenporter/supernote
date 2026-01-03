import hashlib

import jwt
import pytest
from aiohttp.test_utils import TestClient

from supernote.client import Client
from supernote.client.auth import ConstantAuth
from supernote.client.device import DeviceClient
from supernote.server.config import ServerConfig
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import JWT_ALGORITHM

USER_A = "user_a@example.com"
USER_B = "user_b@example.com"


@pytest.fixture
def mock_storage() -> None:
    """Stop the default directory creation."""
    pass


@pytest.fixture
def test_users() -> list[str]:
    return [USER_A, USER_B]


async def register_session(
    coordination_service: CoordinationService, user: str, secret: str
) -> dict[str, str]:
    """Register a session for a user."""
    token = jwt.encode({"sub": user}, secret, algorithm=JWT_ALGORITHM)
    session_val = f"{user}|"
    await coordination_service.set_value(f"session:{token}", session_val, ttl=3600)
    return {"x-access-token": token}


async def test_multi_user_content_with_same_hash(
    client: TestClient,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    blob_storage: BlobStorage,
    create_test_user: None,
) -> None:
    """Test that users uploading same content (same hash) share blob but don't clobber."""
    # Setup Users
    headers_a = await register_session(
        coordination_service, USER_A, server_config.auth.secret_key
    )
    token_a = headers_a["x-access-token"]

    headers_b = await register_session(
        coordination_service, USER_B, server_config.auth.secret_key
    )
    token_b = headers_b["x-access-token"]

    base_url = str(client.make_url(""))

    client_a = Client(client.session, auth=ConstantAuth(token_a), host=base_url)
    file_client_a = DeviceClient(client_a)

    client_b = Client(client.session, auth=ConstantAuth(token_b), host=base_url)
    file_client_b = DeviceClient(client_b)

    # Common Content
    common_content = b"Shared Content Block"
    common_hash = hashlib.md5(common_content).hexdigest()

    # User A uploads
    await file_client_a.upload_content(
        path="/doc_a.txt",
        content=common_content,
        equipment_no="EQ001",
    )

    # User B uploads SAME content
    await file_client_b.upload_content(
        path="/doc_b.txt",
        content=common_content,
        equipment_no="EQ002",
    )

    # Verify Blob Exists
    assert await blob_storage.exists(common_hash)

    # User A Deletes their file
    # Get ID first
    info_a = await file_client_a.query_by_path(path="/doc_a.txt", equipment_no="EQ001")
    assert info_a.entries_vo
    file_id_a = info_a.entries_vo.id

    await file_client_a.delete(id=int(file_id_a), equipment_no="EQ001")

    # Verify Blob STILL Exists (User B still has it)
    # Note: Our current simple implementation might NOT ref-count blobs,
    # but it definitively should NOT delete the blob if another user has it.
    # Actually, the current deletion logic (in FileService/VFS) usually just marks VFS node as valid='N' (recycle bin)
    # or deletes the node. It generally does NOT delete the physical blob immediately unless a GC runs.
    # However, IF it did attempt to delete the blob, we want to ensure it doesn't break User B.

    assert await blob_storage.exists(common_hash), (
        "Blob should persist after User A delete"
    )

    # User B should still be able to download/read
    # We can check by downloading or just ensuring existence is enough for now logic-wise.
    downloaded_b = await file_client_b.download_content(
        path="/doc_b.txt", equipment_no="EQ002"
    )
    assert downloaded_b == common_content


async def test_multi_user_content_with_same_paths(
    client: TestClient,
    create_test_user: None,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    """Test that users can upload distrinct content with the same path."""
    # Setup Users
    headers_a = await register_session(
        coordination_service, USER_A, server_config.auth.secret_key
    )
    token_a = headers_a["x-access-token"]

    headers_b = await register_session(
        coordination_service, USER_B, server_config.auth.secret_key
    )
    token_b = headers_b["x-access-token"]

    base_url = str(client.make_url(""))

    client_a = Client(client.session, auth=ConstantAuth(token_a), host=base_url)
    file_client_a = DeviceClient(client_a)

    client_b = Client(client.session, auth=ConstantAuth(token_b), host=base_url)
    file_client_b = DeviceClient(client_b)

    # User A uploads a file
    filename = "shared.note"
    content_a = b"User A content"
    hash_a = hashlib.md5(content_a).hexdigest()

    await file_client_a.upload_content(
        path=f"/{filename}",
        content=content_a,
        equipment_no="EQ001",
    )

    # User A list files should see their file
    entries_a = await file_client_a.list_folder(path="/", equipment_no="EQ001")
    assert [e.name for e in entries_a.entries] == ["shared.note"]

    # User B list files should NOT see User A's file
    entries_b = await file_client_b.list_folder(path="/", equipment_no="EQ002")
    assert [e.name for e in entries_b.entries] == []

    # User B uploads a file with the same name
    content_b = b"Content from User B"
    hash_b = hashlib.md5(content_b).hexdigest()

    await file_client_b.upload_content(
        path=f"/{filename}",
        content=content_b,
        equipment_no="EQ002",
    )

    # 4. User A queries their file - SHOULD STILL HAVE THEIR CONTENT
    # explicit query call wrapper doesn't verify hash automatically, we check return
    info_a = await file_client_a.query_by_path(
        path=f"/{filename}", equipment_no="EQ001"
    )
    assert info_a.entries_vo
    assert info_a.entries_vo.content_hash == hash_a, (
        "User A's file should NOT be clobbered by User B"
    )

    # 5. User B queries their file - SHOULD HAVE THEIR CONTENT
    info_b = await file_client_b.query_by_path(
        path=f"/{filename}", equipment_no="EQ002"
    )
    assert info_b.entries_vo
    assert info_b.entries_vo.content_hash == hash_b, (
        "User B should have their own file content"
    )
