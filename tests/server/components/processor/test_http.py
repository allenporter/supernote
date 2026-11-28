"""HTTP platform tests for `supernote.server.components.processor.http`."""

from __future__ import annotations

from aiohttp.test_utils import TestClient

from supernote.client.admin import AdminClient
from supernote.client.extended import ExtendedClient
from supernote.models.base import ProcessingStatus, TaskEntityType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager


async def test_processor_http_routes_tasks_and_status(
    extended_client: ExtendedClient,
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Processor HTTP platform serves system tasks and file processing status."""
    file_id = 8801
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                storage_key="k8801",
                file_name="Daily.note",
                directory_id=0,
                is_active="Y",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                entity_id=file_id,
                task_type="HASHING",
                key="global",
                status=ProcessingStatus.COMPLETED.value,
                data="v3",
            )
        )
        await session.commit()

    tasks_vo = await extended_client.list_system_tasks()
    assert len(tasks_vo.tasks) == 1
    assert tasks_vo.tasks[0].task_type == "HASHING"
    assert tasks_vo.tasks[0].status == ProcessingStatus.COMPLETED
    assert tasks_vo.tasks[0].entity_type == TaskEntityType.FILE.value
    assert tasks_vo.tasks[0].entity_id == file_id

    status_vo = await extended_client.get_processing_status([file_id])
    assert status_vo.status_map == {str(file_id): ProcessingStatus.COMPLETED}

    bad_resp = await client.post(
        "/api/extended/file/processing/status",
        json={"bad": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400


async def test_admin_tasks_endpoint_exposes_entity_type_and_entity_id(
    admin_client: AdminClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Admin tasks endpoint exposes entityType/entityId and sets fileId only for file tasks."""
    async with session_manager.session() as session:
        session.add_all(
            [
                SystemTaskDO(
                    user_id=test_user_id,
                    entity_type=TaskEntityType.FILE.value,
                    entity_id=8802,
                    task_type="HASHING",
                    key="global",
                    status=ProcessingStatus.COMPLETED.value,
                ),
                SystemTaskDO(
                    user_id=test_user_id,
                    entity_type=TaskEntityType.SUMMARY.value,
                    entity_id=9901,
                    task_type="SUMMARY_OCR",
                    key="global",
                    status=ProcessingStatus.COMPLETED.value,
                ),
            ]
        )
        await session.commit()

    admin_tasks = await admin_client.list_tasks()
    by_type = {t.task_type: t for t in admin_tasks.tasks}
    assert by_type["SUMMARY_OCR"].entity_type == "summary"
    assert by_type["SUMMARY_OCR"].entity_id == 9901
    assert by_type["SUMMARY_OCR"].file_id is None
    assert by_type["HASHING"].entity_type == "file"
    assert by_type["HASHING"].entity_id == 8802
    assert by_type["HASHING"].file_id == 8802
