import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO


async def test_schedule_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for ScheduleTaskDO and ScheduleTaskGroupDO."""
    # Create Group
    group = ScheduleTaskGroupDO(user_id=999, title="My Tasks")
    db_session.add(group)
    await db_session.commit()

    # Create Task
    task = ScheduleTaskDO(
        user_id=999,
        task_list_id=group.task_list_id,
        title="Buy Milk",
        due_time=int(time.time() * 1000),
    )
    db_session.add(task)
    await db_session.commit()

    # Verify
    stmt = select(ScheduleTaskDO).where(ScheduleTaskDO.task_id == task.task_id)
    result = await db_session.execute(stmt)
    fetched_task = result.scalar_one()

    assert fetched_task.title == "Buy Milk"
    assert fetched_task.task_list_id == group.task_list_id
