from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.device import DeviceDO
from supernote.server.db.models.user import UserDO


async def test_device_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for DeviceDO."""
    user = UserDO(email="device_user@example.com", password_md5="hash")
    db_session.add(user)
    await db_session.commit()

    device = DeviceDO(user_id=user.id, equipment_no="EQ123456")
    db_session.add(device)
    await db_session.commit()

    stmt = select(DeviceDO).where(DeviceDO.id == device.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.user_id == user.id
    assert fetched.equipment_no == "EQ123456"
    assert "EQ123456" in repr(fetched)
