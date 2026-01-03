import hashlib
from typing import Any

import jwt
import pytest
from sqlalchemy import delete

from supernote.client.admin import AdminClient
from supernote.client.client import Client
from supernote.models.user import UserRegisterDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import JWT_ALGORITHM, UserService


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
    pw_md5 = hashlib.md5("pw".encode()).hexdigest()
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
        "password": hashlib.md5("password".encode()).hexdigest(),
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


@pytest.fixture
def admin_client(authenticated_client: Client) -> AdminClient:
    return AdminClient(authenticated_client)


@pytest.mark.asyncio
async def test_admin_update_password(admin_client: AdminClient) -> None:
    md5_pwd = hashlib.md5("newpass123".encode()).hexdigest()
    await admin_client.update_password(md5_pwd)


@pytest.mark.asyncio
async def test_admin_unregister(admin_client: AdminClient) -> None:
    await admin_client.unregister()
