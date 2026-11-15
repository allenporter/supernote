import asyncio
import shutil
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient
from sqlalchemy import delete, update

from supernote.client.device import DeviceClient
from supernote.models.socket import (
    SocketIoAction,
    SocketIoMessageType,
    SocketMessageData,
)
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import FILE_SERVICE_KEY, SOCKETIO_MANAGER_KEY
from supernote.server.routes.file_device import SYNC_LOCK_KEY_PREFIX, SYNC_LOCK_TIMEOUT
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import RECYCLE_RETENTION_MS, FileService
from supernote.server.services.user import UserService


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

    # 2. Add a dummy file before initial sync completes
    await device_client.upload_content(
        "Note/test.note", b"content", equipment_no="test"
    )

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is False  # Still False before synchronous/end completes

    # 3. Interrupted/failed sync (flag="N") must not mark initial sync completed
    await device_client.sync_end("SN123456", flag="N")

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is False

    # 4. Complete sync (flag="Y") marks initial sync completed
    await device_client.sync_end("SN123456", flag="Y")

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is True

    # 5. If storage becomes empty again, sync initialization is reset
    await device_client.sync_end("SN123456", flag="Y")
    async with session_manager.session() as session:
        await session.execute(delete(UserFileDO))
        await session.commit()

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is False

    await device_client.sync_end("SN123456", flag="N")
    await device_client.upload_content(
        "Note/test2.note", b"content2", equipment_no="test"
    )
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is False


async def test_sync_lock(
    client: TestClient,
    auth_headers: dict[str, str],
    coordination_service: CoordinationService,
    user_service: UserService,
) -> None:
    user_id = await user_service.get_user_id("test@example.com")
    lock_key = f"{SYNC_LOCK_KEY_PREFIX}{user_id}"

    with patch.object(
        client.app[SOCKETIO_MANAGER_KEY], "send_message", new_callable=AsyncMock
    ) as mock_send_message:
        # 1. Start sync from SN123 -> stored in CoordinationService (no Socket.IO event emitted on start)
        resp = await client.post(
            "/api/file/2/files/synchronous/start",
            json={"equipmentNo": "SN123"},
            headers=auth_headers,
        )
        assert resp.status == 200
        assert await coordination_service.get_value(lock_key) == "SN123"
        mock_send_message.assert_not_awaited()

        # 2. Try sync from SN456 (same user), should get 409 without overwriting lock
        resp = await client.post(
            "/api/file/2/files/synchronous/start",
            json={"equipmentNo": "SN456"},
            headers=auth_headers,
        )
        assert resp.status == 409
        data = await resp.json()
        assert data["errorCode"] == "E0078"
        assert await coordination_service.get_value(lock_key) == "SN123"

        # 3. End sync from SN123 -> clears lock in CoordinationService and emits STARTSYNC via LocalEventBus
        resp = await client.post(
            "/api/file/2/files/synchronous/end",
            json={"equipmentNo": "SN123", "flag": "true"},
            headers=auth_headers,
        )
        assert resp.status == 200
        assert await coordination_service.get_value(lock_key) is None
        await asyncio.sleep(0)
        mock_send_message.assert_awaited_once()
        assert mock_send_message.await_args is not None
        end_user, end_msg = mock_send_message.await_args.args
        assert end_user == user_id
        assert isinstance(end_msg, SocketMessageData)
        assert end_msg.msg_type == SocketIoMessageType.FILE_SYN
        assert len(end_msg.data) == 1
        assert end_msg.data[0].message_type == SocketIoAction.STARTSYNC
        assert end_msg.data[0].equipment_no == "SN123"

    # 4. Now SN456 should be able to sync
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    assert (await resp.json())["success"] is True
    assert await coordination_service.get_value(lock_key) == "SN456"
    assert SYNC_LOCK_TIMEOUT == 300


async def test_sync_end_opportunistic_recycle_cleanup(
    client: TestClient,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify device sync completion (synchronous/end) opportunistically purges >30-day recycle bin items."""
    file_service: FileService = client.app[FILE_SERVICE_KEY]
    user_email = "test@example.com"

    expired_upload = await device_client.upload_content(
        "/expired_sync.note", b"expired sync content", equipment_no="SN123"
    )
    recent_upload = await device_client.upload_content(
        "/recent_sync.note", b"recent sync content", equipment_no="SN123"
    )
    assert expired_upload.id is not None
    assert recent_upload.id is not None
    expired_id = int(expired_upload.id)
    recent_id = int(recent_upload.id)

    expired_info = await file_service.get_file_info_by_id(user_email, expired_id)
    recent_info = await file_service.get_file_info_by_id(user_email, recent_id)
    assert expired_info and expired_info.storage_key
    assert recent_info and recent_info.storage_key
    expired_key = expired_info.storage_key
    recent_key = recent_info.storage_key

    # Delete both files via device API (moves them to recycle bin)
    await device_client.delete(id=expired_id, equipment_no="SN123")
    await device_client.delete(id=recent_id, equipment_no="SN123")

    # Backdate expired_id's delete_time beyond the 30-day retention window
    expired_time = int(time.time() * 1000) - RECYCLE_RETENTION_MS - 10_000
    async with session_manager.session() as session:
        await session.execute(
            update(RecycleFileDO)
            .where(RecycleFileDO.file_id == expired_id)
            .values(delete_time=expired_time)
        )
        await session.commit()

    # Complete device sync without opening the Web UI Recycle Bin tab
    await device_client.sync_end("SN123", flag="Y")

    # Verify expired item and its blob were purged, while recent item survives
    assert await blob_storage.exists(USER_DATA_BUCKET, expired_key) is False
    assert await blob_storage.exists(USER_DATA_BUCKET, recent_key) is True

    recycled = await file_service.list_recycle(user_email)
    assert [r.name for r in recycled] == ["recent_sync.note"]
