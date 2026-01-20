import time

import pytest

from supernote.client.client import Client
from supernote.models.extended import SystemTaskListVO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager


@pytest.fixture
def system_tasks_url() -> str:
    return "/api/extended/system/tasks"


async def test_list_system_tasks(
    authenticated_client: Client,
    system_tasks_url: str,
    session_manager: DatabaseSessionManager,
) -> None:
    # 1. Seed some system tasks
    async with session_manager.session() as session:
        # Create a pending task
        t1 = SystemTaskDO(
            file_id=101,
            task_type="OCR",
            key="page_1",
            status="PENDING",
            retry_count=0,
            update_time=int(time.time() * 1000),
        )
        session.add(t1)

        # Create a failed task
        t2 = SystemTaskDO(
            file_id=102,
            task_type="SUMMARY",
            key="global",
            status="FAILED",
            retry_count=3,
            last_error="Timeout",
            update_time=int(time.time() * 1000),
        )
        session.add(t2)
        await session.commit()

    # 2. Call the API
    # Since we didn't add this to ExtendedClient yet, use client directly or update client.
    # Let's use authenticated_client.get_json mapping to VO.

    resp = await authenticated_client.get_json(system_tasks_url, SystemTaskListVO)

    assert resp.success
    assert len(resp.tasks) >= 2

    # Verify content
    ocr_tasks = [t for t in resp.tasks if t.task_type == "OCR"]
    assert len(ocr_tasks) >= 1
    assert ocr_tasks[0].status == "PENDING"

    failed_tasks = [t for t in resp.tasks if t.status == "FAILED"]
    assert len(failed_tasks) >= 1
    assert failed_tasks[0].last_error == "Timeout"
