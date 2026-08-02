from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.user import DEFAULT_QUOTA, UserDO


async def test_user_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for UserDO."""
    user = UserDO(
        email="test_user@example.com",
        password_md5="5f4dcc3b5aa765d61d8327deb882cf99",
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.commit()

    stmt = select(UserDO).where(UserDO.id == user.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.email == "test_user@example.com"
    assert fetched.display_name == "Test User"
    assert fetched.total_capacity == str(DEFAULT_QUOTA)
    assert fetched.is_active is True
    assert fetched.is_admin is False
    assert f"<UserDO(id={user.id}, email='test_user@example.com')>" in repr(fetched)
