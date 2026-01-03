import pytest

from supernote.models.user import UserRegisterDTO
from supernote.server.config import AuthConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService


@pytest.fixture
def test_users() -> list[str]:
    """Fixture to clear all test users.

    We use this to verify we can bootstrap properly.
    """
    return []


async def test_bootstrap_first_user_is_admin(
    session_manager: DatabaseSessionManager, coordination_service: CoordinationService
) -> None:
    """Test that the first registered user becomes an admin."""
    config = AuthConfig(enable_registration=True)
    service = UserService(config, coordination_service, session_manager)

    # Register first user (should be admin)
    dto1 = UserRegisterDTO(
        email="admin@example.com", password="password", user_name="Admin"
    )
    user1 = await service.register(dto1)
    assert user1.is_admin is True

    # Register second user (should NOT be admin)
    dto2 = UserRegisterDTO(
        email="user@example.com", password="password", user_name="User"
    )
    user2 = await service.register(dto2)
    assert user2.is_admin is False


async def test_bootstrap_bypasses_disabled_registration(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Test that bootstrapping works even if registration is disabled."""
    # Config has registration DISABLED
    config = AuthConfig(enable_registration=False)
    service = UserService(config, coordination_service, session_manager)

    # Register first user (should succeed because of bootstrap)
    dto1 = UserRegisterDTO(
        email="bootstrap@example.com", password="password", user_name="Bootstrap"
    )
    user1 = await service.register(dto1)

    assert user1.is_admin is True

    # Register second user (should FAIL because registration is disabled)
    dto2 = UserRegisterDTO(
        email="fail@example.com", password="password", user_name="Fail"
    )
    with pytest.raises(ValueError, match="Registration is disabled"):
        await service.register(dto2)


@pytest.mark.asyncio
async def test_admin_create_user_bypass(
    session_manager: DatabaseSessionManager, coordination_service: CoordinationService
) -> None:
    """Test that create_user allows creating users when disabled."""
    config = AuthConfig(enable_registration=False)
    service = UserService(config, coordination_service, session_manager)

    # Bootstrap first
    await service.register(
        UserRegisterDTO(email="admin@example.com", password="pw", user_name="Admin")
    )

    # Explicitly use create_user (Admin action simulation)
    dto2 = UserRegisterDTO(email="new@example.com", password="pw", user_name="New")
    user2 = await service.create_user(dto2)

    assert user2.email == "new@example.com"
