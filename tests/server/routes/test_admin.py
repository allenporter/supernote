import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import delete, select

from supernote.client.admin import AdminClient
from supernote.client.client import Client
from supernote.models.base import ProcessingStatus
from supernote.models.user import UserRegisterDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import JWT_ALGORITHM, UserService
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.paths import get_hermes_summary_id


@pytest.fixture
def admin_headers(server_config: ServerConfig) -> dict[str, Any]:
    """Headers for an ADMIN user."""
    secret = server_config.auth.secret_key
    token = jwt.encode({"sub": "admin@example.com"}, secret, algorithm=JWT_ALGORITHM)
    return {"x-access-token": token}


@pytest.fixture
def user_headers(server_config: ServerConfig) -> dict[str, Any]:
    """Headers for a NORMAL user."""
    secret = server_config.auth.secret_key
    token = jwt.encode({"sub": "user@example.com"}, secret, algorithm=JWT_ALGORITHM)
    return {"x-access-token": token}


async def setup_users(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    """Helper to setup database state."""
    async with session_manager.session() as session:
        await session.execute(delete(UserDO))
        await session.commit()

    service = UserService(server_config.auth, coordination_service, session_manager)

    # Register Admin (Bootstrapping)
    pw_md5 = hashlib.md5(b"pw").hexdigest()
    await service.register(
        UserRegisterDTO(email="admin@example.com", password=pw_md5, user_name="Admin")
    )

    # Register Normal User (via Admin creation to ensure consistency,
    # though strict bootstrapping only allows the FIRST user to be admin,
    # so we use create_user for the second one if we wanted,
    # but here we just need to ensure the DB state is correct).
    # Easier: manually set is_admin=False for the second user if needed,
    # but register() naturally makes 2nd user non-admin.
    await service.register(
        UserRegisterDTO(email="user@example.com", password=pw_md5, user_name="User")
    )

    # Store sessions in coordination service
    secret = server_config.auth.secret_key
    admin_token = jwt.encode(
        {"sub": "admin@example.com"}, secret, algorithm=JWT_ALGORITHM
    )
    user_token = jwt.encode(
        {"sub": "user@example.com"}, secret, algorithm=JWT_ALGORITHM
    )

    await coordination_service.set_value(
        f"session:{admin_token}", "admin@example.com|", ttl=3600
    )
    await coordination_service.set_value(
        f"session:{user_token}", "user@example.com|", ttl=3600
    )


async def test_admin_list_users_permission(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test access control for listing users."""
    await setup_users(session_manager, coordination_service, server_config)

    # 1. Admin should succeed
    resp = await client.get("/api/admin/users", headers=admin_headers)
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 2

    # 2. Normal user should fail
    resp = await client.get("/api/admin/users", headers=user_headers)
    assert resp.status == 403

    # 3. Anon should fail
    resp = await client.get("/api/admin/users")
    assert resp.status == 401


async def test_admin_create_user(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """Test admin creating a user."""
    await setup_users(session_manager, coordination_service, server_config)

    new_user = {
        "email": "newbie@example.com",
        "userName": "Newbie",
        "password": hashlib.md5(b"password").hexdigest(),
        "countryCode": "1",
    }

    # Admin creates user
    resp = await client.post("/api/admin/users", json=new_user, headers=admin_headers)
    assert resp.status == 200

    # Verify user exists
    resp = await client.get("/api/admin/users", headers=admin_headers)
    data = await resp.json()
    emails = [u["email"] for u in data]
    assert "newbie@example.com" in emails


async def test_admin_update_password(admin_client: AdminClient) -> None:
    md5_pwd = hashlib.md5(b"newpass123").hexdigest()
    await admin_client.update_password(md5_pwd)


async def test_admin_unregister(admin_client: AdminClient) -> None:
    await admin_client.unregister()


async def test_admin_force_password_reset(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """Test admin force-resetting a user's password."""
    await setup_users(session_manager, coordination_service, server_config)

    # 1. Reset user password
    target_email = "user@example.com"
    new_pw = hashlib.md5(b"reset123").hexdigest()

    resp = await client.post(
        "/api/admin/users/password",
        json={"email": target_email, "password": new_pw},
        headers=admin_headers,
    )
    assert resp.status == 200

    # 2. Verify user can login with new password logic (simulated by checking DB)
    async with session_manager.session() as session:
        result = await session.execute(
            select(UserDO).where(UserDO.email == target_email)
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.password_md5 == new_pw


async def test_admin_queue_control(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test stopping, starting, and getting queue status."""
    await setup_users(session_manager, coordination_service, server_config)

    # 1. Access control tests
    # Non-admin status get should fail
    resp = await client.get("/api/admin/queue/status", headers=user_headers)
    assert resp.status == 403

    # Non-admin stop should fail
    resp = await client.post("/api/admin/queue/stop", headers=user_headers)
    assert resp.status == 403

    # Non-admin start should fail
    resp = await client.post("/api/admin/queue/start", headers=user_headers)
    assert resp.status == 403

    # 2. Admin functionality tests
    # Admin status should succeed, default should be running (paused=False)
    resp = await client.get("/api/admin/queue/status", headers=admin_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["paused"] is False
    assert data["queueSize"] == 0
    assert data["processingFiles"] == []

    # Stop queue
    resp = await client.post("/api/admin/queue/stop", headers=admin_headers)
    assert resp.status == 200

    # Status should now show paused
    resp = await client.get("/api/admin/queue/status", headers=admin_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["paused"] is True

    # Start queue
    resp = await client.post("/api/admin/queue/start", headers=admin_headers)
    assert resp.status == 200

    # Status should show running again
    resp = await client.get("/api/admin/queue/status", headers=admin_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["paused"] is False


async def test_admin_reprocess(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test admin reprocess endpoint (permission and functionality)."""
    await setup_users(session_manager, coordination_service, server_config)

    # Insert a dummy SystemTaskDO
    async with session_manager.session() as session:
        task = SystemTaskDO(
            file_id=999,
            task_type="SUMMARY_GENERATION",
            key="global",
            status=ProcessingStatus.COMPLETED,
            update_time=12345,
        )
        session.add(task)
        await session.commit()

    # 1. Non-admin should fail (403)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "summary", "file_id": 999},
        headers=user_headers,
    )
    assert resp.status == 403

    # 2. Admin should succeed (200)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "summary", "file_id": 999},
        headers=admin_headers,
    )
    assert resp.status == 200

    # 3. Verify task is deleted in DB
    async with session_manager.session() as session:
        result = await session.execute(
            select(SystemTaskDO).where(SystemTaskDO.file_id == 999)
        )
        tasks = result.scalars().all()
        assert len(tasks) == 0

    # 4. Admin with invalid task type should fail (400)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "invalid_type", "file_id": 999},
        headers=admin_headers,
    )
    assert resp.status == 400


async def _get_admin_user_id(session_manager: DatabaseSessionManager) -> int:
    """Helper to fetch the bootstrapped admin's numeric user ID."""
    async with session_manager.session() as session:
        result = await session.execute(
            select(UserDO).where(UserDO.email == "admin@example.com")
        )
        return result.scalar_one().id


async def test_admin_hermes_summary_retry_happy_path(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """A stale COMPLETED task + Hermes summary hash both get invalidated, and
    the file is re-enqueued, when retried.
    """
    await setup_users(session_manager, coordination_service, server_config)
    admin_user_id = await _get_admin_user_id(session_manager)

    file_id = 5001
    storage_key = "storage-key-5001"
    hermes_uuid = get_hermes_summary_id(storage_key)

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=admin_user_id,
                file_name="notebook.note",
                storage_key=storage_key,
                directory_id=0,
            )
        )
        session.add(
            SystemTaskDO(
                file_id=file_id,
                task_type="HERMES_SUMMARY_GENERATION",
                key="global",
                status=ProcessingStatus.COMPLETED,
                last_error=None,
                update_time=12345,
            )
        )
        # A previously-generated Hermes summary whose stored source hash
        # would otherwise make HermesSummaryModule.process() skip
        # regeneration on the next run, since that hash (not the task's
        # COMPLETED status) is what actually gates it.
        session.add(
            SummaryDO(
                user_id=admin_user_id,
                file_id=file_id,
                unique_identifier=hermes_uuid,
                data_source="HERMES_INTERPRETATION",
                content="Old interpretation",
                extra_metadata=json.dumps({"source_hash": "stale-hash"}),
            )
        )
        await session.commit()

    with patch.object(
        client.app["processor_service"], "enqueue_file", new=AsyncMock()
    ) as mock_enqueue:
        resp = await client.post(
            f"/api/admin/notes/{file_id}/hermes-summary/retry",
            headers=admin_headers,
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["fileId"] == file_id
        assert data["task"]["status"] == "PENDING"
        assert data["task"]["lastError"] is None
        mock_enqueue.assert_awaited_once_with(file_id)

    async with session_manager.session() as session:
        result = await session.execute(
            select(SystemTaskDO)
            .where(SystemTaskDO.file_id == file_id)
            .where(SystemTaskDO.task_type == "HERMES_SUMMARY_GENERATION")
        )
        task = result.scalar_one()
        assert task.status == ProcessingStatus.PENDING
        assert task.last_error is None

        result = await session.execute(
            select(SummaryDO).where(SummaryDO.unique_identifier == hermes_uuid)
        )
        summary = result.scalar_one()
        # Content (used as a context hint for the next Hermes call) is kept...
        assert summary.content == "Old interpretation"
        # ...but the stale source hash is cleared so the next pipeline run
        # actually regenerates instead of short-circuiting on a hash match.
        assert json.loads(summary.extra_metadata or "{}").get("source_hash") is None


async def test_admin_hermes_summary_retry_no_prior_task(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """A file with no prior Hermes task still succeeds and gets enqueued."""
    await setup_users(session_manager, coordination_service, server_config)
    admin_user_id = await _get_admin_user_id(session_manager)

    file_id = 5002
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=admin_user_id,
                file_name="fresh.note",
                storage_key="storage-key-5002",
                directory_id=0,
            )
        )
        await session.commit()

    with patch.object(
        client.app["processor_service"], "enqueue_file", new=AsyncMock()
    ) as mock_enqueue:
        resp = await client.post(
            f"/api/admin/notes/{file_id}/hermes-summary/retry",
            headers=admin_headers,
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["task"]["status"] == "PENDING"
        assert data["task"]["lastError"] is None
        mock_enqueue.assert_awaited_once_with(file_id)


async def test_admin_hermes_summary_retry_nonexistent_file(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """Retrying a nonexistent file_id returns 404."""
    await setup_users(session_manager, coordination_service, server_config)

    resp = await client.post(
        "/api/admin/notes/999999999/hermes-summary/retry",
        headers=admin_headers,
    )
    assert resp.status == 404


async def test_admin_hermes_summary_retry_permission(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Access control matches other admin routes: 401 anon, 403 non-admin."""
    await setup_users(session_manager, coordination_service, server_config)
    admin_user_id = await _get_admin_user_id(session_manager)

    file_id = 5003
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=admin_user_id,
                file_name="permissions.note",
                storage_key="storage-key-5003",
                directory_id=0,
            )
        )
        await session.commit()

    path = f"/api/admin/notes/{file_id}/hermes-summary/retry"

    # Anon should fail
    resp = await client.post(path)
    assert resp.status == 401

    # Non-admin should fail
    resp = await client.post(path, headers=user_headers)
    assert resp.status == 403


async def test_admin_recycle_bin_cleanup_run_purges_expired_entries(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
) -> None:
    """The manual cleanup trigger purges only entries past the retention window."""
    await setup_users(session_manager, coordination_service, server_config)
    admin_user_id = await _get_admin_user_id(session_manager)

    async with session_manager.session() as session:
        vfs = VirtualFileSystem(session)
        old_file = await vfs.create_or_update_file(
            admin_user_id,
            0,
            "old.note",
            size=1,
            md5="h1",
            storage_key="cleanup-old-key",
        )
        await vfs.delete_node(admin_user_id, old_file.id)

        new_file = await vfs.create_or_update_file(
            admin_user_id,
            0,
            "new.note",
            size=1,
            md5="h2",
            storage_key="cleanup-new-key",
        )
        await vfs.delete_node(admin_user_id, new_file.id)

        # Backdate only the "old" entry past the configured retention window.
        result = await session.execute(
            select(RecycleFileDO).where(RecycleFileDO.file_id == old_file.id)
        )
        old_entry = result.scalar_one()
        old_entry.delete_time -= (
            (server_config.recycle_bin_cleanup_retention_days + 1) * 86400 * 1000
        )
        await session.commit()

    resp = await client.post(
        "/api/admin/recycle-bin/cleanup/run", headers=admin_headers
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["purgedCount"] == 1

    async with session_manager.session() as session:
        result = await session.execute(
            select(UserFileDO).where(UserFileDO.id == old_file.id)
        )
        assert result.scalar_one_or_none() is None

        result = await session.execute(
            select(UserFileDO).where(UserFileDO.id == new_file.id)
        )
        assert result.scalar_one_or_none() is not None


async def test_admin_recycle_bin_cleanup_run_permission(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Access control matches other admin routes: 401 anon, 403 non-admin."""
    await setup_users(session_manager, coordination_service, server_config)

    path = "/api/admin/recycle-bin/cleanup/run"

    resp = await client.post(path)
    assert resp.status == 401

    resp = await client.post(path, headers=user_headers)
    assert resp.status == 403
