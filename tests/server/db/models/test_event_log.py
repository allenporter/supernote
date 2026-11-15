"""Unit tests for UserEventDO ORM persistence and monotonic sequence behavior."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.event_log import UserEventDO


async def test_user_event_crud_and_non_recycled_autoincrement(
    db_session: AsyncSession,
) -> None:
    """Verify UserEventDO stores JSON payloads and never recycles deleted seq IDs."""
    first = UserEventDO(
        user_id=1,
        timestamp_ms=1_700_000_000_000,
        event_type="vfs.created",
        actor="user:web",
        entity_type="file",
        entity_id="101",
        related_file_id=101,
        payload={"path": "/NOTE/todo.note", "is_folder": False},
    )
    db_session.add(first)
    await db_session.commit()
    first_seq = first.seq
    assert first_seq >= 1

    fetched = (
        await db_session.execute(
            select(UserEventDO).where(UserEventDO.seq == first_seq)
        )
    ).scalar_one()
    assert fetched.user_id == 1
    assert fetched.event_type == "vfs.created"
    assert fetched.related_file_id == 101
    assert fetched.payload == {"path": "/NOTE/todo.note", "is_folder": False}

    # Deleting the highest row must not cause sqlite_autoincrement to reuse first_seq.
    await db_session.execute(delete(UserEventDO).where(UserEventDO.seq == first_seq))
    await db_session.commit()

    second = UserEventDO(
        user_id=1,
        timestamp_ms=1_700_000_000_500,
        event_type="schedule.task_created",
        actor="user:web",
        entity_type="schedule_task",
        entity_id="task-1",
    )
    db_session.add(second)
    await db_session.commit()
    assert second.seq > first_seq
    assert second.payload == {}
