import asyncio
import hashlib
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import delete, select

from supernote.client.admin import AdminClient
from supernote.client.auth import ConstantAuth
from supernote.client.client import Client
from supernote.client.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from supernote.models.base import ProcessingStatus
from supernote.models.user import UserRegisterDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import Event, NoteUpdatedEvent
from supernote.server.keys import EVENT_BUS_KEY
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService


@pytest.fixture
async def setup_users(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> tuple[str, str]:
    """Setup admin and normal users and return their session tokens."""
    async with session_manager.session() as session:
        await session.execute(delete(UserDO))
        await session.commit()

    service = UserService(server_config.auth, coordination_service, session_manager)

    # Register Admin (Bootstrapping)
    pw_md5 = hashlib.md5(b"pw").hexdigest()
    await service.register(
        UserRegisterDTO(email="admin@example.com", password=pw_md5, user_name="Admin")
    )

    # Register Normal User
    await service.register(
        UserRegisterDTO(email="user@example.com", password=pw_md5, user_name="User")
    )

    admin_token = await service.create_session("admin@example.com")
    user_token = await service.create_session("user@example.com")
    return admin_token, user_token


@pytest.fixture
def admin_headers(setup_users: tuple[str, str]) -> dict[str, Any]:
    """Headers for an ADMIN user."""
    admin_token, _ = setup_users
    return {"x-access-token": admin_token}


@pytest.fixture
def user_headers(setup_users: tuple[str, str]) -> dict[str, Any]:
    """Headers for a NORMAL user."""
    _, user_token = setup_users
    return {"x-access-token": user_token}


@pytest.fixture
def admin_api_client(client: TestClient, setup_users: tuple[str, str]) -> AdminClient:
    """AdminClient authenticated as an ADMIN user."""
    admin_token, _ = setup_users
    base_url = str(client.make_url(""))
    return AdminClient(
        Client(client.session, auth=ConstantAuth(admin_token), host=base_url)
    )


@pytest.fixture
def user_api_client(client: TestClient, setup_users: tuple[str, str]) -> AdminClient:
    """AdminClient authenticated as a NORMAL (non-admin) user."""
    _, user_token = setup_users
    base_url = str(client.make_url(""))
    return AdminClient(
        Client(client.session, auth=ConstantAuth(user_token), host=base_url)
    )


async def test_admin_list_users_permission(
    client: Client,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test access control for listing users."""
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
    admin_headers: dict[str, str],
) -> None:
    """Test admin creating a user."""

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


async def test_admin_clear_account(admin_client: AdminClient) -> None:
    await admin_client.clear_account(confirm=True)


async def test_admin_force_password_reset(
    client: Client,
    session_manager: DatabaseSessionManager,
    admin_headers: dict[str, str],
) -> None:
    """Test admin force-resetting a user's password."""
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
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test stopping, starting, and getting queue status."""
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
    client: TestClient,
    session_manager: DatabaseSessionManager,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    """Test admin reprocess endpoint (permission and functionality)."""
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

    # Non-admin should fail (403)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "summary", "file_id": 999},
        headers=user_headers,
    )
    assert resp.status == 403

    # Admin should succeed (200)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "summary", "file_id": 999},
        headers=admin_headers,
    )
    assert resp.status == 200

    # Verify task is deleted in DB
    async with session_manager.session() as session:
        result = await session.execute(
            select(SystemTaskDO).where(SystemTaskDO.file_id == 999)
        )
        tasks = result.scalars().all()
        assert len(tasks) == 0

    # Admin with invalid task type should fail (400)
    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "invalid_type", "file_id": 999},
        headers=admin_headers,
    )
    assert resp.status == 400

    # Global reprocess should only trigger active .note files, skipping soft-deleted notes
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=8001,
                user_id=1,
                file_name="active_note.note",
                storage_key="k1",
                md5="m1",
                is_active="Y",
            )
        )
        session.add(
            UserFileDO(
                id=8002,
                user_id=1,
                file_name="inactive_note.note",
                storage_key="k2",
                md5="m2",
                is_active="N",
            )
        )
        await session.commit()

    published_ids: list[int] = []

    async def capture_updated(event: Event) -> None:
        if isinstance(event, NoteUpdatedEvent):
            published_ids.append(event.file_id)

    assert client.app is not None
    client.app[EVENT_BUS_KEY].subscribe(NoteUpdatedEvent, capture_updated)

    resp = await client.post(
        "/api/admin/reprocess",
        json={"task_type": "summary"},
        headers=admin_headers,
    )
    assert resp.status == 200
    await asyncio.sleep(0)
    assert 8001 in published_ids
    assert 8002 not in published_ids


async def test_admin_integrity(
    admin_api_client: AdminClient,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Test admin integrity endpoint returns report via AdminClient."""
    user_id = await user_service.get_user_id("user@example.com")
    assert user_id is not None
    user_report = await admin_api_client.verify_integrity(email="user@example.com")
    assert user_report.success is True
    assert user_report.scanned == 8
    assert user_report.ok == 8
    assert user_report.issues == []

    async with session_manager.session() as session:
        result = await session.execute(
            select(UserFileDO.id).where(UserFileDO.user_id == user_id).limit(1)
        )
        folder_id = result.scalar_one()

    file_report = await admin_api_client.verify_integrity(
        email="user@example.com", file_id=folder_id
    )
    assert file_report.scanned == 1
    assert file_report.ok == 1

    full_report = await admin_api_client.verify_integrity(full_disk=True)
    assert full_report.success is True
    assert full_report.scanned >= 16  # Admin + User default folders
    assert full_report.ok == full_report.scanned
    assert full_report.issues == []

    with pytest.raises(NotFoundException):
        await admin_api_client.verify_integrity(email="nonexistent@example.com")


async def test_admin_integrity_permission(
    user_api_client: AdminClient,
) -> None:
    """Test non-admin user cannot access integrity endpoint."""
    with pytest.raises(ForbiddenException):
        await user_api_client.verify_integrity(email="user@example.com")


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"email": ""},
        {"email": "user@example.com", "file_id": "abc"},
        {"full_disk": "1"},
        {"full_disk": "yes"},
        {"full_disk": "invalid"},
        {"full_disk": "true", "email": "user@example.com"},
        {"full_disk": "true", "file_id": "1"},
    ],
)
async def test_admin_integrity_invalid_params(
    admin_api_client: AdminClient,
    params: dict[str, str],
) -> None:
    """Test missing or invalid email / file_id query parameters return 400."""
    with pytest.raises(BadRequestException):
        await admin_api_client.client.get("/api/admin/integrity", params=params)


async def test_admin_list_tasks(
    session_manager: DatabaseSessionManager,
    admin_api_client: AdminClient,
) -> None:
    """Test admin list tasks endpoint and filters via AdminClient."""
    async with session_manager.session() as session:
        session.add_all(
            [
                SystemTaskDO(
                    file_id=101,
                    task_type="OCR_EXTRACTION",
                    key="page_1",
                    status=ProcessingStatus.FAILED,
                    retry_count=2,
                    last_error="API timeout",
                    update_time=2000,
                ),
                SystemTaskDO(
                    file_id=102,
                    task_type="SUMMARY_GENERATION",
                    key="global",
                    status=ProcessingStatus.COMPLETED,
                    retry_count=0,
                    update_time=3000,
                ),
            ]
        )
        await session.commit()

    resp = await admin_api_client.list_tasks(
        status="failed", file_id=101, task_type="ocr"
    )
    assert len(resp.tasks) == 1
    assert resp.tasks[0].file_id == 101
    assert resp.tasks[0].last_error == "API timeout"


async def test_admin_list_tasks_permission(
    user_api_client: AdminClient,
) -> None:
    """Test non-admin user cannot list system tasks."""
    with pytest.raises(ForbiddenException):
        await user_api_client.list_tasks()


@pytest.mark.parametrize(
    ("status", "task_type"),
    [
        ("bogus", None),
        (None, "bogus"),
    ],
)
async def test_admin_list_tasks_invalid_filters(
    admin_api_client: AdminClient,
    status: str | None,
    task_type: str | None,
) -> None:
    """Test invalid filter parameters raise BadRequestException."""
    with pytest.raises(BadRequestException):
        await admin_api_client.list_tasks(status=status, task_type=task_type)


async def test_admin_set_user_quota(
    client: TestClient,
    admin_api_client: AdminClient,
    user_api_client: AdminClient,
    admin_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
) -> None:
    """Test setting and resetting per-user storage quota via the Admin API."""
    await admin_api_client.admin_set_quota("user@example.com", 5 * 1024**3)
    async with session_manager.session() as session:
        user = (
            await session.execute(
                select(UserDO).where(UserDO.email == "user@example.com")
            )
        ).scalar_one()
        assert user.total_capacity == str(5 * 1024**3)

    await admin_api_client.admin_set_quota("user@example.com", 0)
    async with session_manager.session() as session:
        user = (
            await session.execute(
                select(UserDO).where(UserDO.email == "user@example.com")
            )
        ).scalar_one()
        assert user.total_capacity == "0"

    with pytest.raises(ForbiddenException):
        await user_api_client.admin_set_quota("user@example.com", 1024)

    with pytest.raises(BadRequestException):
        await admin_api_client.admin_set_quota("missing@example.com", 1024)

    with pytest.raises(BadRequestException):
        await admin_api_client.admin_set_quota("user@example.com", -10)

    bad_resp = await client.post(
        "/api/admin/users/quota",
        json={"email": "user@example.com", "totalCapacity": "not-an-int"},
        headers=admin_headers,
    )
    assert bad_resp.status == 400

    empty_email_resp = await client.post(
        "/api/admin/users/quota",
        json={"email": "", "totalCapacity": 100},
        headers=admin_headers,
    )
    assert empty_email_resp.status == 400
