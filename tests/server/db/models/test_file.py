from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import CapacityDO, RecycleFileDO, UserFileDO


async def test_user_file_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for UserFileDO."""
    # Create
    file_do = UserFileDO(
        user_id=12345,
        directory_id=0,
        file_name="test.txt",
        is_folder="N",
        size=1024,
        md5="abc12345",
    )
    db_session.add(file_do)
    await db_session.commit()

    # Read
    stmt = select(UserFileDO).where(UserFileDO.id == file_do.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.file_name == "test.txt"
    assert fetched.user_id == 12345
    assert fetched.create_time > 0
    assert fetched.id > 0  # unique_id check

    # Update
    fetched.file_name = "updated.txt"
    await db_session.commit()

    stmt = select(UserFileDO).where(UserFileDO.id == file_do.id)
    result = await db_session.execute(stmt)
    updated = result.scalar_one()
    assert updated.file_name == "updated.txt"


async def test_capacity_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for CapacityDO."""
    cap = CapacityDO(user_id=12345, used_capacity=500, total_capacity=10000)
    db_session.add(cap)
    await db_session.commit()

    stmt = select(CapacityDO).where(CapacityDO.user_id == 12345)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.used_capacity == 500
    assert fetched.total_capacity == 10000


async def test_recycle_file_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for RecycleFileDO."""
    recycle = RecycleFileDO(
        file_id=100,
        user_id=12345,
        file_name="deleted.txt",
        size=2048,
        is_folder="N",
    )
    db_session.add(recycle)
    await db_session.commit()

    stmt = select(RecycleFileDO).where(RecycleFileDO.id == recycle.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.file_id == 100
    assert fetched.file_name == "deleted.txt"
    assert fetched.delete_time > 0
