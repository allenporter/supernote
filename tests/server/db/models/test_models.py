import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.schedule import ScheduleTaskDO, ScheduleTaskGroupDO


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
    assert fetched.id > 0  # Snowflake check

    # Update
    fetched.file_name = "updated.txt"
    await db_session.commit()

    stmt = select(UserFileDO).where(UserFileDO.id == file_do.id)
    result = await db_session.execute(stmt)
    updated = result.scalar_one()
    assert updated.file_name == "updated.txt"


async def test_schedule_crud(db_session: AsyncSession) -> None:
    """Test Basic CRUD for ScheduleTaskDO."""
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
