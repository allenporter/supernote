import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.client.web import WebClient
from supernote.server.db.models.note_processing import SystemTaskDO


@pytest.mark.asyncio
async def test_web_upload_triggers_processing(
    web_client: WebClient,
    db_session: "AsyncSession",
) -> None:
    """Verify that uploading a .note file via web API triggers processing."""

    # Upload a .note file
    file_name = "test_web_trigger.note"
    await web_client.upload_file(
        parent_id=0, name=file_name, content=b"dummy note content"
    )

    # Check if tasks were created
    # We wait for the asynchronous event bus to process the event
    max_retries = 10
    found_tasks = False
    file_id = None

    for _ in range(max_retries):
        # We need to find the file_id first
        from supernote.server.db.models.file import UserFileDO

        stmt = select(UserFileDO.id).where(UserFileDO.file_name == file_name)
        res = await db_session.execute(stmt)
        file_id = res.scalar()

        if file_id:
            stmt_tasks = select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
            res_tasks = await db_session.execute(stmt_tasks)
            tasks = res_tasks.scalars().all()
            if tasks:
                found_tasks = True
                break
        await asyncio.sleep(0.5)

    assert found_tasks, (
        f"No system tasks were created for the web-uploaded .note file (file_id: {file_id})"
    )
    print(f"Verified: Tasks created for file_id {file_id}")
