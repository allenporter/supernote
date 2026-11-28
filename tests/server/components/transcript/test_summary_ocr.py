"""Tests for `SummaryOcrModule` Digest handwriting OCR under `ProcessorService`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from supernote.models.base import ProcessingStatus, TaskEntityType, TaskType
from supernote.models.summary import AddSummaryDTO, UpdateSummaryDTO
from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.processor import (
    PROCESSOR_SERVICE_KEY,
    ProcessorWorkItem,
)
from supernote.server.components.summary import SUMMARY_SERVICE_KEY
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.utils.tasks import get_task
from tests.fixtures.server import TEST_USERNAME
from tests.server.components.conftest import LoadComponents

DIGEST_MARK = "schaefer-dev/garmin_connect_20260016.pdf.mark"
TWO_PAGE_MARK = "philips/blank-a6x-3.26.40-two-pages.note"
FAKE_OCR_CONFIG = {
    "ai": {
        "ocr": {
            "provider": "fake_ai",
            "model": "fake-ocr-v1",
        }
    }
}


async def _drain_processor(component_core: ServerCore) -> None:
    """Wait for all pending event-bus handlers and processor queue items to finish."""
    await component_core.event_bus.wait_idle()
    processor = component_core.app[PROCESSOR_SERVICE_KEY]
    await asyncio.wait_for(processor.queue.join(), timeout=10.0)


async def test_summary_create_triggers_processor_ocr_and_persists_transcript(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Creating a digest with handwriting runs SummaryOcrModule and persists transcript + task."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_v1.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-ocr-create-1",
            content="Highlighted excerpt",
            source_path="/Document/Garmin_Connect.pdf",
            handwrite_inner_name="digest_v1.mark",
            handwrite_md5="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    transcript = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript is not None
    assert transcript.summary_id == created.id
    assert transcript.handwrite_md5 == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert transcript.model_id == "fake-ocr-v1"
    assert transcript.text.startswith("Transcribed (")

    task = await get_task(
        session_manager,
        test_user_id,
        created.id,
        TaskType.SUMMARY_OCR,
        "global",
    )
    assert task is not None
    assert task.entity_type == TaskEntityType.SUMMARY.value
    assert task.status == ProcessingStatus.COMPLETED


async def test_summary_update_same_md5_skips_reocr(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Re-triggering an update with the same handwrite_md5 is a no-op."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_same.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-ocr-same-1",
            content="Excerpt",
            handwrite_inner_name="digest_same.mark",
            handwrite_md5="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    transcript_v1 = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_v1 is not None

    await summary_service.update_summary(
        TEST_USERNAME,
        UpdateSummaryDTO(
            id=created.id,
            comment_str="Updated comment only",
            handwrite_inner_name="digest_same.mark",
            handwrite_md5="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ),
    )
    await _drain_processor(component_core)

    transcript_after = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_after == transcript_v1


async def test_summary_update_new_md5_reruns_ocr_and_updates_transcript(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Updating handwrite_md5 re-runs OCR and updates the stored transcript."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    mark_bytes = (test_data_dir / DIGEST_MARK).read_bytes()
    await blob_storage.put(USER_DATA_BUCKET, "digest_u1.mark", mark_bytes)
    await blob_storage.put(USER_DATA_BUCKET, "digest_u2.mark", mark_bytes)

    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-ocr-update-1",
            content="Excerpt",
            handwrite_inner_name="digest_u1.mark",
            handwrite_md5="cccccccccccccccccccccccccccccccc",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    await summary_service.update_summary(
        TEST_USERNAME,
        UpdateSummaryDTO(
            id=created.id,
            handwrite_inner_name="digest_u2.mark",
            handwrite_md5="dddddddddddddddddddddddddddddddd",
        ),
    )
    await _drain_processor(component_core)

    transcript_v2 = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_v2 is not None
    assert transcript_v2.handwrite_md5 == "dddddddddddddddddddddddddddddddd"
    assert transcript_v2.model_id == "fake-ocr-v1"
    assert transcript_v2.text.startswith("Transcribed (")


async def test_summary_update_clearing_handwriting_deletes_stale_transcript(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Clearing handwriting on a summary removes its previously stored transcript."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_clear.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-ocr-clear-1",
            content="Excerpt",
            handwrite_inner_name="digest_clear.mark",
            handwrite_md5="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)
    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is not None
    )

    await summary_service.update_summary(
        TEST_USERNAME,
        UpdateSummaryDTO(
            id=created.id,
            handwrite_inner_name="",
            handwrite_md5="",
        ),
    )
    await _drain_processor(component_core)
    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )


async def test_summary_ocr_noop_when_ocr_model_unconfigured(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """No transcript is stored when no OCR model is configured."""
    await load_components("processor", "summary", "transcript")
    assert component_core.app[OCR_MODEL_KEY] is None

    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_no_ocr.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-no-ocr-1",
            content="Excerpt",
            handwrite_inner_name="digest_no_ocr.mark",
            handwrite_md5="11111111111111111111111111111111",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )


async def test_summary_ocr_noop_without_handwriting(
    component_core: ServerCore,
    load_components: LoadComponents,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Summaries without handwriting do not enqueue OCR tasks or store transcripts."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-text-only-1",
            content="Text-only digest",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )
    assert (
        await get_task(
            session_manager, test_user_id, created.id, TaskType.SUMMARY_OCR, "global"
        )
        is None
    )


async def test_summary_ocr_joins_multiple_pages(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Multi-page handwriting annotations OCR each page and join text cleanly."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_two_pages.mark",
        (test_data_dir / TWO_PAGE_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-multipage-1",
            content="Multi-page annotation",
            handwrite_inner_name="digest_two_pages.mark",
            handwrite_md5="44444444444444444444444444444444",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    transcript = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript is not None
    pages = transcript.text.split("\n\n")
    assert len(pages) == 2
    assert all(p.startswith("Transcribed (") for p in pages)


async def test_recover_missing_tasks_backfills_untranscribed_summaries(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """recover_missing_tasks discovers and enqueues existing handwritten summaries lacking transcripts."""
    await load_components(
        "ai",
        "fake_ai",
        "processor",
        "summary",
        "transcript",
        configs=FAKE_OCR_CONFIG,
        start=False,
    )
    processor = component_core.app[PROCESSOR_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_backfill.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    async with session_manager.session() as session:
        summary_do = SummaryDO(
            user_id=test_user_id,
            unique_identifier="digest-backfill-1",
            content="Pre-existing handwritten digest",
            handwrite_inner_name="digest_backfill.mark",
            handwrite_md5="55555555555555555555555555555555",
            is_summary_group=False,
            is_deleted=False,
        )
        session.add(summary_do)
        await session.commit()
        summary_id = int(summary_do.id)

    await processor.recover_missing_tasks(user_id=test_user_id)
    assert (
        ProcessorWorkItem(TaskEntityType.SUMMARY, test_user_id, summary_id)
        in processor.processing_entities
    )

    ok = await processor.process_entity(
        TaskEntityType.SUMMARY, summary_id, user_id=test_user_id
    )
    assert ok is True
    transcript = await transcript_service.get_summary_transcript(
        test_user_id, summary_id
    )
    assert transcript is not None
    assert transcript.handwrite_md5 == "55555555555555555555555555555555"


async def test_summary_ocr_missing_blob_marks_task_failed_and_skips_missing_recovery(
    component_core: ServerCore,
    load_components: LoadComponents,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Missing `.mark` blob marks SUMMARY_OCR task FAILED and is not re-enqueued by missing-task recovery."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]
    processor = component_core.app[PROCESSOR_SERVICE_KEY]

    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-missing-blob-1",
            content="Missing mark blob",
            handwrite_inner_name="does_not_exist.mark",
            handwrite_md5="66666666666666666666666666666666",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)

    task = await get_task(
        session_manager, test_user_id, created.id, TaskType.SUMMARY_OCR, "global"
    )
    assert task is not None
    assert task.status == ProcessingStatus.FAILED
    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )

    await processor.pause()
    await processor.recover_missing_tasks(user_id=test_user_id)
    assert (
        ProcessorWorkItem(TaskEntityType.SUMMARY, test_user_id, created.id)
        not in processor.processing_entities
    )


async def test_summary_deleted_cleans_up_system_task_checkpoint(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Deleting a summary cleans up both its transcript and its SUMMARY_OCR SystemTaskDO checkpoint."""
    await load_components(
        "ai", "fake_ai", "processor", "summary", "transcript", configs=FAKE_OCR_CONFIG
    )
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_del.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-delete-cleanup-1",
            content="Delete me",
            handwrite_inner_name="digest_del.mark",
            handwrite_md5="77777777777777777777777777777777",
        ),
    )
    assert created.id is not None
    await _drain_processor(component_core)
    assert (
        await get_task(
            session_manager, test_user_id, created.id, TaskType.SUMMARY_OCR, "global"
        )
        is not None
    )

    await summary_service.delete_summary(TEST_USERNAME, created.id)
    await _drain_processor(component_core)

    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )
    assert (
        await get_task(
            session_manager, test_user_id, created.id, TaskType.SUMMARY_OCR, "global"
        )
        is None
    )
