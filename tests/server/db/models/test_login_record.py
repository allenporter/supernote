from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.login_record import LoginRecordDO
from supernote.server.db.models.user import UserDO


async def test_login_record_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for LoginRecordDO."""
    user = UserDO(email="login_user@example.com", password_md5="hash")
    db_session.add(user)
    await db_session.commit()

    record = LoginRecordDO(
        user_id=user.id,
        login_method="password",
        equipment="Supernote A5X",
        ip="127.0.0.1",
        create_time="1700000000",
    )
    db_session.add(record)
    await db_session.commit()

    stmt = select(LoginRecordDO).where(LoginRecordDO.id == record.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.user_id == user.id
    assert fetched.login_method == "password"
    assert fetched.equipment == "Supernote A5X"
    assert fetched.ip == "127.0.0.1"
    assert "<LoginRecordDO(user_id=" in repr(fetched)
