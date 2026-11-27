"""Tests for system task persistence utilities."""

from supernote.models.base import ProcessingStatus, TaskEntityType, TaskType
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.tasks import get_task, update_task_status


async def test_get_and_update_task_status(
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify update_task_status inserts and updates status, data, and last_error."""
    user_id = 42
    entity_id = 500
    task_type = "EMBEDDING_GENERATION"
    key = "page_p0"

    assert await get_task(session_manager, user_id, entity_id, task_type, key) is None

    await update_task_status(
        session_manager,
        user_id=user_id,
        entity_id=entity_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v1",
    )

    task = await get_task(session_manager, user_id, entity_id, task_type, key)
    assert task is not None
    assert task.user_id == user_id
    assert task.entity_type == TaskEntityType.FILE.value
    assert task.entity_id == entity_id
    assert task.task_type == task_type
    assert task.key == key
    assert task.status == ProcessingStatus.COMPLETED
    assert task.data == "model-v1"
    assert task.last_error is None
    assert (
        await get_task(session_manager, user_id + 1, entity_id, task_type, key) is None
    )

    await update_task_status(
        session_manager,
        user_id=user_id,
        entity_id=entity_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v2",
    )

    updated = await get_task(session_manager, user_id, entity_id, task_type, key)
    assert updated is not None
    assert updated.id == task.id
    assert updated.status == ProcessingStatus.COMPLETED
    assert updated.data == "model-v2"
    assert updated.last_error is None

    await update_task_status(
        session_manager,
        user_id=user_id,
        entity_id=entity_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.FAILED,
        error="boom",
    )

    failed = await get_task(session_manager, user_id, entity_id, task_type, key)
    assert failed is not None
    assert failed.id == task.id
    assert failed.status == ProcessingStatus.FAILED
    assert failed.data is None
    assert failed.last_error == "boom"
    assert failed.retry_count == 0

    await update_task_status(
        session_manager,
        user_id=user_id,
        entity_id=entity_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.FAILED,
        error="boom again",
    )
    retried = await get_task(session_manager, user_id, entity_id, task_type, key)
    assert retried is not None
    assert retried.retry_count == 1
    assert retried.last_error == "boom again"

    await update_task_status(
        session_manager,
        user_id=user_id,
        entity_id=entity_id,
        task_type=task_type,
        key=key,
        status=ProcessingStatus.COMPLETED,
        data="model-v2",
    )
    recovered = await get_task(session_manager, user_id, entity_id, task_type, key)
    assert recovered is not None
    assert recovered.retry_count == 0
    assert recovered.last_error is None


async def test_task_status_isolates_entity_types_with_same_id(
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify tasks with identical (user_id, entity_id, task_type, key) are isolated by entity_type."""
    user_id = 42
    shared_id = 9001
    task_type = "CUSTOM_TASK"
    key = "global"

    assert TaskType.entity_type_for(TaskType.OCR_EXTRACTION) == TaskEntityType.FILE
    assert TaskType.entity_type_for("UNKNOWN_PLUGIN_TASK") == TaskEntityType.FILE

    await update_task_status(
        session_manager,
        user_id,
        shared_id,
        task_type,
        key,
        ProcessingStatus.COMPLETED,
        data="file-v1",
        entity_type=TaskEntityType.FILE,
    )
    await update_task_status(
        session_manager,
        user_id,
        shared_id,
        task_type,
        key,
        ProcessingStatus.FAILED,
        error="summary-err",
        entity_type=TaskEntityType.SUMMARY,
    )

    file_task = await get_task(
        session_manager,
        user_id,
        shared_id,
        task_type,
        key,
        entity_type=TaskEntityType.FILE,
    )
    summary_task = await get_task(
        session_manager,
        user_id,
        shared_id,
        task_type,
        key,
        entity_type=TaskEntityType.SUMMARY,
    )
    assert file_task is not None
    assert summary_task is not None
    assert file_task.id != summary_task.id
    assert file_task.entity_type == TaskEntityType.FILE.value
    assert file_task.status == ProcessingStatus.COMPLETED
    assert summary_task.entity_type == TaskEntityType.SUMMARY.value
    assert summary_task.status == ProcessingStatus.FAILED
    assert summary_task.last_error == "summary-err"
