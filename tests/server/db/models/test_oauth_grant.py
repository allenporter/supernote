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
            refresh_token_hash="f" * 64,
            created_at=1700000000,
            expires_at=1702592000,
        )
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(OAuthGrantDO).where(
                OAuthGrantDO.user_id == user.id, OAuthGrantDO.id == "0a1b2c3d4e5f6a7b"
            )
        )
    ).scalar_one()

    assert (fetched.access_token_hash, fetched.access_expires_at) == (None, None)
    assert fetched.last_used_at is None
    assert repr(fetched) == (
        f"<OAuthGrantDO(user_id={user.id}, id='0a1b2c3d4e5f6a7b', "
        "client_id='https://client.example.com/')>"
    )
