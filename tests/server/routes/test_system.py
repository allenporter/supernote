import time

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.models.extended import SystemTaskListVO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager


@pytest.fixture
def system_tasks_url() -> str:
    return "/api/extended/system/tasks"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/js/main.js",
        "/static/style.css",
    ],
)
async def test_static_and_index_cache_control_headers(
    client: TestClient, path: str
) -> None:
    """Verify GET / and /static/ assets include Cache-Control: no-cache."""
    resp = await client.get(path)
    assert resp.status == 200
    assert resp.headers.get("Cache-Control") == "no-cache"


async def test_list_system_tasks(
    authenticated_client: Client,
    system_tasks_url: str,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    # 1. Seed some system tasks
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=test_user_id,
                file_name="Note101.note",
                directory_id=0,
            )
        )
        session.add(
            UserFileDO(
                id=102,
                user_id=test_user_id,
                file_name="Note102.note",
                directory_id=0,
            )
        )
        # Create a pending task
        t1 = SystemTaskDO(
            user_id=test_user_id,
            entity_id=101,
            task_type="OCR",
            key="page_1",
            status="PENDING",
            retry_count=0,
            update_time=int(time.time() * 1000),
        )
        session.add(t1)

        # Create a failed task
        t2 = SystemTaskDO(
            user_id=test_user_id,
            entity_id=102,
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
