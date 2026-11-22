from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.oauth_grant import OAuthGrantDO
from supernote.server.db.models.user import UserDO


async def test_oauth_grant_crud(db_session: AsyncSession) -> None:
    """Test basic CRUD for OAuthGrantDO."""
    user = UserDO(email="grant_model@example.com", password_md5="hash")
    db_session.add(user)
    await db_session.commit()

    db_session.add(
        OAuthGrantDO(
            user_id=user.id,
            id="0a1b2c3d4e5f6a7b",
            client_id="https://client.example.com/",
            scopes="supernote:all",
            created_at=1700000000,
            last_used_at=None,
            expires_at=1702592000,
        )
    )
    await db_session.commit()

    stmt = select(OAuthGrantDO).where(
        OAuthGrantDO.user_id == user.id, OAuthGrantDO.id == "0a1b2c3d4e5f6a7b"
    )
    fetched = (await db_session.execute(stmt)).scalar_one()

    assert fetched.client_id == "https://client.example.com/"
    assert fetched.scopes == "supernote:all"
    assert fetched.created_at == 1700000000
    assert fetched.last_used_at is None
    assert fetched.expires_at == 1702592000
    assert "0a1b2c3d4e5f6a7b" in repr(fetched)
