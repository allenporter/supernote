from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.summary import SummaryDO, SummaryTagDO


async def test_summary_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for SummaryDO."""
    summary = SummaryDO(
        user_id=100,
        name="Meeting Summary",
        unique_identifier="uuid-summary-1",
        content="Discussion notes",
    )
    db_session.add(summary)
    await db_session.commit()

    stmt = select(SummaryDO).where(SummaryDO.id == summary.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.user_id == 100
    assert fetched.name == "Meeting Summary"
    assert fetched.unique_identifier == "uuid-summary-1"
    assert fetched.content == "Discussion notes"


async def test_summary_tag_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for SummaryTagDO."""
    tag = SummaryTagDO(
        user_id=100,
        name="Work",
        unique_identifier="uuid-tag-1",
    )
    db_session.add(tag)
    await db_session.commit()

    stmt = select(SummaryTagDO).where(SummaryTagDO.id == tag.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.user_id == 100
    assert fetched.name == "Work"
    assert fetched.unique_identifier == "uuid-tag-1"
