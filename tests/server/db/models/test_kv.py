from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.kv import KeyValueDO


async def test_key_value_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for KeyValueDO."""
    kv = KeyValueDO(key="token_123", value="valid", expiry=1700000000.0)
    db_session.add(kv)
    await db_session.commit()

    stmt = select(KeyValueDO).where(KeyValueDO.key == "token_123")
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.value == "valid"
    assert fetched.expiry == 1700000000.0
    assert "<KeyValueDO(key='token_123'" in repr(fetched)
