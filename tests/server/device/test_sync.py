import shutil
from pathlib import Path

from aiohttp.test_utils import TestClient
from sqlalchemy import delete

from supernote.client.device import DeviceClient
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager


async def test_sync_start_syn_type(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    # Clear storage root for test
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    # Clear VFS state for this user
    async with session_manager.session() as session:
        # Delete all nodes for simplicity. In a real shared DB this would be bad,
        # but here we are in a test environment with a shared in-memory DB.
        # Ideally we filter by user_id but we need to resolve it first.
        await session.execute(delete(UserFileDO))
        await session.commit()
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is False  # Empty storage

    # 2. Add a dummy file
    await device_client.upload_content("Note/test.note", "content", equipment_no="test")

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is True  # Non-empty storage


async def test_sync_lock(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 1. Start sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 2. Try sync from SN456 (same user), should get 409
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 409
    data = await resp.json()
    assert data["errorCode"] == "E0078"

    # 3. End sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123", "flag": "true"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 4. Now SN456 should be able to sync
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    assert (await resp.json())["success"] is True
