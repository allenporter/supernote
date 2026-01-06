import hashlib

import pytest
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService


@pytest.mark.asyncio
async def test_retrieve_password_success(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    # Setup
    email = "forgot@example.com"
    old_pw = hashlib.md5("old".encode()).hexdigest()
    new_pw = hashlib.md5("new".encode()).hexdigest()

    # Create user directly in DB
    async with session_manager.session() as session:
        user = UserDO(
            email=email, password_md5=old_pw, display_name="Forgot", is_active=True
        )
        session.add(user)
        await session.commit()

    # Validation: Pass scalars
    result: bool = await user_service.retrieve_password(email, new_pw)
    assert result is True

    # Verify in DB
    async with session_manager.session() as session:
        user_result = await session.execute(select(UserDO).where(UserDO.email == email))
        user = user_result.scalar_one()
        assert user.password_md5 == new_pw


@pytest.mark.asyncio
async def test_retrieve_password_invalid_md5(user_service: UserService) -> None:
    with pytest.raises(ValueError, match="Invalid password format"):
        await user_service.retrieve_password("user@example.com", "plain_text_password")


@pytest.mark.asyncio
async def test_retrieve_password_user_not_found(user_service: UserService) -> None:
    result = await user_service.retrieve_password(
        "nonexistent@example.com", hashlib.md5("pw".encode()).hexdigest()
    )
    assert result is False
