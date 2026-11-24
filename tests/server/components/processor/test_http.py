"""HTTP platform tests for `supernote.server.components.processor.http`."""

from __future__ import annotations

from aiohttp.test_utils import TestClient

from supernote.client.extended import ExtendedClient
from supernote.models.base import ProcessingStatus
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager


async def test_processor_http_routes_tasks_status_and_metadata(
    extended_client: ExtendedClient,
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Processor HTTP platform serves system tasks, file processing status, and notebook metadata."""
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
                file_id=file_id,
                task_type="HASHING",
                key="global",
                status=ProcessingStatus.COMPLETED.value,
                data="v2",
            )
        )
        session.add(
            NoteMetadataDO(
                user_id=test_user_id,
                file_id=file_id,
                native_file_id="F8801",
                file_type="NOTE",
                signature="SN_FILE_VER_20230015",
                total_pages=1,
                header_json='{"APPLY_EQUIPMENT": "N5"}',
                footer_json="{}",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=test_user_id,
                file_id=file_id,
                page_index=0,
                page_id="P1",
                content_hash="h1",
                page_style="style_white",
                has_ink=True,
                has_drawables=True,
                page_json="{}",
                keywords_json="[]",
                titles_json="[]",
                links_json="[]",
            )
        )
        await session.commit()

    tasks_vo = await extended_client.list_system_tasks()
    assert len(tasks_vo.tasks) == 1
    assert tasks_vo.tasks[0].task_type == "HASHING"
    assert tasks_vo.tasks[0].status == ProcessingStatus.COMPLETED

    status_vo = await extended_client.get_processing_status([file_id])
    assert status_vo.status_map == {str(file_id): ProcessingStatus.COMPLETED}

    meta_vo = await extended_client.get_note_metadata(file_id)
    assert meta_vo.total_pages == 1
    assert meta_vo.equipment == "N5"

    bad_resp = await client.post(
        "/api/extended/file/processing/status",
        json={"bad": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400
