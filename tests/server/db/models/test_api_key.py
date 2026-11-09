from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.api_key import ApiKeyDO
from supernote.server.db.models.user import UserDO


async def test_api_key_crud(db_session: AsyncSession) -> None:
    """Test basic CRUD for ApiKeyDO."""
    user = UserDO(email="apikey_model@example.com", password_md5="hash")
    db_session.add(user)
    await db_session.commit()

    api_key = ApiKeyDO(
        user_id=user.id,
        id="a1b2c3d4e5f6",
        name="Headless CLI",
        key_prefix="sn_01234567...",
        sha256_hash="0" * 64,
        created_at=1700000000,
        last_used_at=None,
        expires_at=1702592000,
    )
    db_session.add(api_key)
    await db_session.commit()

    stmt = select(ApiKeyDO).where(
        ApiKeyDO.user_id == user.id, ApiKeyDO.id == "a1b2c3d4e5f6"
    )
    fetched = (await db_session.execute(stmt)).scalar_one()

    assert fetched.user_id == user.id
    assert fetched.id == "a1b2c3d4e5f6"
    assert fetched.name == "Headless CLI"
    assert fetched.key_prefix == "sn_01234567..."
    assert fetched.sha256_hash == "0" * 64
    assert fetched.created_at == 1700000000
    assert fetched.last_used_at is None
    assert fetched.expires_at == 1702592000
    assert "a1b2c3d4e5f6" in repr(fetched)
