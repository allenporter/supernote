"""Tests for system task persistence utilities."""

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.db.models.note_processing import NoteMetadataDO, NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.tasks import (
    get_task,
    has_incomplete_page_ocr,
    update_task_status,
)


async def test_get_and_update_task_status(
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify update_task_status inserts and updates status, data, and last_error."""
    file_id = 500
    task_type = "EMBEDDING_GENERATION"
    key = "page_p0"

    assert await get_task(session_manager, file_id, task_type, key) is None

    # Insert initial COMPLETED task with model version in data
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v1",
    )

    task = await get_task(session_manager, file_id, task_type, key)
    assert task is not None
    assert task.file_id == file_id
    assert task.task_type == task_type
    assert task.key == key
    assert task.status == ProcessingStatus.COMPLETED
    assert task.data == "model-v1"
    assert task.last_error is None

    # Upsert on conflict to update data to a new model version
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v2",
    )

    updated = await get_task(session_manager, file_id, task_type, key)
    assert updated is not None
    assert updated.id == task.id
    assert updated.status == ProcessingStatus.COMPLETED
    assert updated.data == "model-v2"
    assert updated.last_error is None

    # Upsert on failure sets last_error and clears data
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.FAILED,
        error="boom",
    )

    failed = await get_task(session_manager, file_id, task_type, key)
    assert failed is not None
    assert failed.id == task.id
    assert failed.status == ProcessingStatus.FAILED
    assert failed.data is None
    assert failed.last_error == "boom"
    assert failed.retry_count == 0

    # Subsequent failure increments retry_count
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.FAILED,
        error="boom again",
    )
    retried = await get_task(session_manager, file_id, task_type, key)
    assert retried is not None
    assert retried.retry_count == 1
    assert retried.last_error == "boom again"

    # Recovery to COMPLETED resets retry_count to 0
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v2",
    )
    recovered = await get_task(session_manager, file_id, task_type, key)
    assert recovered is not None
    assert recovered.retry_count == 0
    assert recovered.last_error is None


async def test_has_incomplete_page_ocr_allows_unhashed_standalone_rows(
    session_manager: DatabaseSessionManager,
) -> None:
    """Standalone NotePageContentDO rows without pipeline metadata are treated as ready."""
    file_id = 505
    async with session_manager.session() as session:
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Seeded text",
            )
        )
        await session.commit()

    async with session_manager.session() as session:
        assert await has_incomplete_page_ocr(session, file_id) is False
        assert await has_incomplete_page_ocr(session, file_id, "p0") is False


async def test_has_incomplete_page_ocr_blocks_missing_ocr_on_hashed_or_deferred_files(
    session_manager: DatabaseSessionManager,
) -> None:
    """Hashed files (including deferred syncs with NoteMetadataDO) require COMPLETED OCR per page."""
    file_id = 506
    async with session_manager.session() as session:
        session.add_all(
            [
                NoteMetadataDO(user_id=1, file_id=file_id, total_pages=2),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    content_hash="h0",
                    text_content="Stale text",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p1",
                    content_hash="h1",
                    text_content="Fresh text",
                ),
            ]
        )
        await session.commit()

    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=TaskType.OCR_EXTRACTION,
        key="page_p1",
        status=ProcessingStatus.COMPLETED,
    )

    async with session_manager.session() as session:
        assert await has_incomplete_page_ocr(session, file_id, "p1") is False
        assert await has_incomplete_page_ocr(session, file_id, "p0") is True
        assert await has_incomplete_page_ocr(session, file_id) is True

    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=TaskType.OCR_EXTRACTION,
        key="page_p0",
        status=ProcessingStatus.COMPLETED,
    )
    async with session_manager.session() as session:
        assert await has_incomplete_page_ocr(session, file_id) is False


async def test_has_incomplete_page_ocr_blocks_failed_prerequisite_tasks(
    session_manager: DatabaseSessionManager,
) -> None:
    """Failed PNG or OCR tasks mark target page and file OCR prerequisites incomplete."""
    file_id = 507
    await update_task_status(
        session_manager,
        file_id=file_id,
        task_type=TaskType.PNG_CONVERSION,
        key="page_p0",
        status=ProcessingStatus.FAILED,
        error="png boom",
    )
    async with session_manager.session() as session:
        assert await has_incomplete_page_ocr(session, file_id, "p0") is True
        assert await has_incomplete_page_ocr(session, file_id) is True
