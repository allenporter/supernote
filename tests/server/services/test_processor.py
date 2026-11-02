import asyncio
import hashlib
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.ocr import ConcurrencyLimitedOcrModel
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    BlobCleanupEvent,
    Event,
    LocalEventBus,
    NoteDeletedEvent,
    NoteProcessingCompletedEvent,
    NoteUpdatedEvent,
    SyncCompletedEvent,
)
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import SqliteCoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.processor_modules.embedding import EmbeddingModule
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> FileService:
    return FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=LocalEventBus(),
    )


@pytest.fixture
def summary_service(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> SummaryService:
    return SummaryService(
        user_service=user_service,
        session_manager=session_manager,
    )


@pytest.fixture(name="processor_service")
def processor_service_fixture(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    summary_service: SummaryService,
) -> ProcessorService:
    return ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )


class SlowModule(ProcessorModule):
    def __init__(self, name: str, sleep_time: float):
        self._name = name
        self.sleep_time = sleep_time
        self.active_count = 0
        self.max_active_seen = 0
        self.calls: list[tuple[int, int | None, str | None]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_type(self) -> TaskType:
        return TaskType.PNG_CONVERSION

    async def run_if_needed(self, *args: object, **kwargs: object) -> bool:
        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.calls.append((file_id, page_index, page_id))
        self.active_count += 1
        self.max_active_seen = max(self.max_active_seen, self.active_count)
        try:
            await asyncio.sleep(self.sleep_time)
        finally:
            self.active_count -= 1


async def test_processor_lifecycle(processor_service: ProcessorService) -> None:
    # Test Start
    await processor_service.start()
    assert len(processor_service.workers) == 2
    assert not processor_service._shutdown_event.is_set()

    # Test Stop
    await processor_service.stop()
    assert processor_service._shutdown_event.is_set()
    for worker in processor_service.workers:
        assert worker.cancelled() or worker.done()


async def test_processor_handles_event(processor_service: ProcessorService) -> None:
    hashing = SlowModule("Hashing", 0.0)
    processor_service.register_modules(hashing=hashing, png=None)
    await processor_service.start()

    event = NoteUpdatedEvent(file_id=123, user_id=1, file_path="test.note")
    await processor_service.event_bus.publish(event)
    await asyncio.sleep(0.1)

    assert hashing.calls == [(123, None, None)]

    await processor_service.stop()


async def test_processor_deduplication(processor_service: ProcessorService) -> None:
    event = NoteUpdatedEvent(file_id=123, user_id=1, file_path="test.note")

    await processor_service.handle_note_updated(event)
    assert 123 in processor_service.processing_files
    assert processor_service.queue.qsize() == 1

    # Second event for same file should be ignored
    await processor_service.handle_note_updated(event)
    assert processor_service.queue.qsize() == 1
    assert await processor_service.queue.get() == 123


async def test_handle_note_deleted_cleanup(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    file_service: FileService,
    summary_service: SummaryService,
    test_user_id: int,
) -> None:
    file_id = 999
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"png0")
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p1"), b"png1")

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                storage_key="delete_test_key",
                file_name="delete_me.note",
                directory_id=0,
            )
        )
        session.add(
            NoteMetadataDO(
                user_id=test_user_id,
                file_id=file_id,
                file_type="note",
                total_pages=2,
                header_json="{}",
                footer_json="{}",
            )
        )
        session.add_all(
            [
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    has_ink=True,
                    has_drawables=True,
                    has_content=True,
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    page_index=1,
                    page_id="p1",
                    has_ink=True,
                    has_drawables=True,
                    has_content=True,
                ),
            ]
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h1",
                text_content="Page 1 text",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="p1",
                content_hash="h2",
                text_content="Page 2 text",
            )
        )

        session.add(
            SystemTaskDO(
                file_id=file_id, task_type="PNG", key="page_0", status="COMPLETED"
            )
        )
        session.add(
            SystemTaskDO(
                file_id=file_id, task_type="OCR", key="page_0", status="COMPLETED"
            )
        )
        await session.commit()

    summary_module = SummaryModule(
        file_service=file_service,
        summary_service=summary_service,
        summary_model=FakeSummaryModel(),
    )
    assert await summary_module.run(file_id, session_manager) is True

    # Attach handwriting blobs to the note's summary and group, plus a shared group with another child
    await blob_storage.put(USER_DATA_BUCKET, "note_sum_hw.bin", b"sum-hw")
    await blob_storage.put(USER_DATA_BUCKET, "note_grp_hw.bin", b"grp-hw")
    await blob_storage.put(USER_DATA_BUCKET, "shared_grp_hw.bin", b"shared-grp-hw")
    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(SummaryDO).where(SummaryDO.user_id == test_user_id)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.is_summary_group:
                row.handwrite_inner_name = "note_grp_hw.bin"
            elif row.file_id == file_id:
                row.handwrite_inner_name = "note_sum_hw.bin"

        # Near-miss: a parent group shared by both file_id and another digest must survive
        session.add_all(
            [
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="shared-grp-uuid",
                    name="Shared Group",
                    is_summary_group=True,
                    handwrite_inner_name="shared_grp_hw.bin",
                ),
                SummaryDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    unique_identifier="deleted-note-in-shared-grp",
                    parent_unique_identifier="shared-grp-uuid",
                    is_summary_group=False,
                ),
                SummaryDO(
                    user_id=test_user_id,
                    file_id=None,
                    unique_identifier="surviving-digest-in-shared-grp",
                    parent_unique_identifier="shared-grp-uuid",
                    is_summary_group=False,
                ),
            ]
        )
        await session.commit()

    # Trigger deletion event
    event = NoteDeletedEvent(file_id=file_id, user_id=test_user_id)
    await processor_service.handle_note_deleted(event)

    # Verify DB records for file_id and its now-empty group are gone, while shared group & surviving child remain
    async with session_manager.session() as session:
        assert await session.get(NoteMetadataDO, (test_user_id, file_id)) is None
        page_metas = (
            (
                await session.execute(
                    select(NotePageMetadataDO).where(
                        NotePageMetadataDO.file_id == file_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(page_metas) == 0
        contents = (
            (
                await session.execute(
                    select(NotePageContentDO).where(
                        NotePageContentDO.file_id == file_id
                    )
                )
            )
            .scalars()
            .all()
        )
        tasks = (
            (
                await session.execute(
                    select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        )
        surviving_uuids = set(
            (
                await session.execute(
                    select(SummaryDO.unique_identifier).where(
                        SummaryDO.user_id == test_user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(contents) == 0
        assert len(tasks) == 0
        assert surviving_uuids == {
            "shared-grp-uuid",
            "surviving-digest-in-shared-grp",
        }

    # Verify Blobs are deleted only for unreferenced note summaries/groups
    assert not await blob_storage.exists(CACHE_BUCKET, get_page_png_path(file_id, "p0"))
    assert not await blob_storage.exists(CACHE_BUCKET, get_page_png_path(file_id, "p1"))
    assert not await blob_storage.exists(USER_DATA_BUCKET, "note_sum_hw.bin")
    assert not await blob_storage.exists(USER_DATA_BUCKET, "note_grp_hw.bin")
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_grp_hw.bin")


async def test_handle_blob_cleanup_event(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
) -> None:
    """Verify BlobCleanupEvent deletes unreferenced blobs while preserving active and soft-deleted file/summary blobs."""
    await blob_storage.put(USER_DATA_BUCKET, "unreferenced_hw.bin", b"orphan")
    await blob_storage.put(USER_DATA_BUCKET, "referenced_by_file.bin", b"file-data")
    await blob_storage.put(
        USER_DATA_BUCKET, "referenced_by_recycled_file.bin", b"recycled-file-data"
    )
    await blob_storage.put(USER_DATA_BUCKET, "referenced_by_summary.bin", b"sum-data")
    await blob_storage.put(
        USER_DATA_BUCKET, "referenced_by_deleted_summary.bin", b"deleted-sum-data"
    )

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=777,
                    user_id=test_user_id,
                    storage_key="referenced_by_file.bin",
                    file_name="keep.note",
                    directory_id=0,
                    is_active="Y",
                ),
                UserFileDO(
                    id=778,
                    user_id=test_user_id,
                    storage_key="referenced_by_recycled_file.bin",
                    file_name="recycled.note",
                    directory_id=0,
                    is_active="N",
                ),
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="keep-summary-uuid",
                    handwrite_inner_name="referenced_by_summary.bin",
                    is_deleted=False,
                ),
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="soft-deleted-summary-uuid",
                    handwrite_inner_name="referenced_by_deleted_summary.bin",
                    is_deleted=True,
                ),
            ]
        )
        await session.commit()

    await processor_service.start()
    try:
        await processor_service.event_bus.publish(
            BlobCleanupEvent(
                storage_keys={
                    "unreferenced_hw.bin",
                    "referenced_by_file.bin",
                    "referenced_by_recycled_file.bin",
                    "referenced_by_summary.bin",
                    "referenced_by_deleted_summary.bin",
                }
            )
        )
        await asyncio.sleep(0.05)
        await processor_service.handle_blob_cleanup(
            BlobCleanupEvent(storage_keys={"referenced_by_file.bin"})
        )
    finally:
        await processor_service.stop()

    assert not await blob_storage.exists(USER_DATA_BUCKET, "unreferenced_hw.bin")
    assert await blob_storage.exists(USER_DATA_BUCKET, "referenced_by_file.bin")
    assert await blob_storage.exists(
        USER_DATA_BUCKET, "referenced_by_recycled_file.bin"
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "referenced_by_summary.bin")
    assert await blob_storage.exists(
        USER_DATA_BUCKET, "referenced_by_deleted_summary.bin"
    )


async def test_page_hashing_orphan_cleanup(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    file_id = 888
    hashing_module = PageHashingModule(file_service=file_service)
    await blob_storage.put(USER_DATA_BUCKET, "key", test_note_path.read_bytes())

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=1,
                file_name="test.note",
                storage_key="key",
                md5="hash",
            )
        )
        await session.commit()

    # Initial hashing populates the real pages from test_note_path
    await hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        real_pages = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        real_page_ids = [p.page_id for p in real_pages]
        assert len(real_page_ids) >= 1

    orphan_page_ids = ["orphan_1", "orphan_2"]
    all_page_ids = [*real_page_ids, *orphan_page_ids]
    for pid in all_page_ids:
        await blob_storage.put(
            CACHE_BUCKET, get_page_png_path(file_id, pid), f"png_{pid}".encode()
        )

    async with session_manager.session() as session:
        for idx, pid in enumerate(orphan_page_ids, start=len(real_page_ids)):
            session.add(
                NotePageContentDO(
                    file_id=file_id,
                    page_index=idx,
                    page_id=pid,
                    content_hash=f"old_{idx}",
                )
            )
        for pid in all_page_ids:
            session.add(
                SystemTaskDO(
                    file_id=file_id,
                    task_type="PNG_CONVERSION",
                    key=f"page_{pid}",
                    status="COMPLETED",
                )
            )
        await session.commit()

    await hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        contents = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert [c.page_id for c in contents] == real_page_ids

        stmt = select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
        tasks = (await session.execute(stmt)).scalars().all()
        assert {t.key for t in tasks} == {f"page_{pid}" for pid in real_page_ids}

    for pid in real_page_ids:
        assert await blob_storage.exists(CACHE_BUCKET, get_page_png_path(file_id, pid))
    for pid in orphan_page_ids:
        assert not await blob_storage.exists(
            CACHE_BUCKET, get_page_png_path(file_id, pid)
        )


async def test_recover_tasks_enqueues_incomplete(
    processor_service: ProcessorService, session_manager: DatabaseSessionManager
) -> None:
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(file_id=1, task_type="PNG", key="page_0", status="FAILED")
        )
        session.add(
            SystemTaskDO(file_id=2, task_type="OCR", key="page_1", status="PENDING")
        )
        session.add(
            SystemTaskDO(
                file_id=3, task_type="EMBEDDING", key="page_0", status="COMPLETED"
            )
        )
        await session.commit()

    await processor_service.recover_tasks()

    assert 1 in processor_service.processing_files
    assert 2 in processor_service.processing_files
    assert 3 not in processor_service.processing_files
    assert processor_service.queue.qsize() == 2

    ids = []
    ids.append(await processor_service.queue.get())
    ids.append(await processor_service.queue.get())
    assert set(ids) == {1, 2}


async def test_start_calls_poll_loop(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
) -> None:
    hashing = SlowModule("Hashing", 0.0)
    processor_service.register_modules(hashing=hashing, png=None)

    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(file_id=1, task_type="PNG", key="page_0", status="FAILED")
        )
        await session.commit()

    await processor_service.start()
    await asyncio.sleep(0.05)

    assert hashing.calls == [(1, None, None)]
    assert processor_service.polling_task is not None
    assert not processor_service.polling_task.done()
    assert len(processor_service.workers) == processor_service.concurrency

    await processor_service.stop()
    assert (
        processor_service.polling_task.cancelled()
        or processor_service.polling_task.done()
    )


async def test_recover_stalled_tasks_time_threshold(
    processor_service: ProcessorService, session_manager: DatabaseSessionManager
) -> None:
    now_ms = int(time.time() * 1000)
    stale_ms = now_ms - (600 * 1000)  # 10 mins ago

    async with session_manager.session() as session:
        # Stalled task (old update time)
        session.add(
            SystemTaskDO(
                file_id=10,
                task_type="PNG",
                key="p0",
                status="PROCESSING",
                update_time=stale_ms,
            )
        )
        # Fresh task (recent update time)
        session.add(
            SystemTaskDO(
                file_id=11,
                task_type="OCR",
                key="p0",
                status="PROCESSING",
                update_time=now_ms,
            )
        )
        await session.commit()

    await processor_service.recover_stalled_tasks()

    assert 10 in processor_service.processing_files
    assert 11 not in processor_service.processing_files
    assert processor_service.queue.qsize() == 1
    assert await processor_service.queue.get() == 10


async def test_page_parallelism(
    processor_service: ProcessorService, session_manager: DatabaseSessionManager
) -> None:
    hashing = SlowModule("Hashing", 0.01)
    png = SlowModule("PNG", 0.1)
    summary = SlowModule("Summary", 0.01)

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=None,
        embedding=None,
        summary=summary,
    )
    processor_service.page_modules = [png]

    file_id = 123
    async with session_manager.session() as session:
        for i in range(4):
            session.add(
                NotePageContentDO(
                    file_id=file_id,
                    page_index=i,
                    page_id=f"p{i}",
                    content_hash=f"h{i}",
                )
            )
        await session.commit()

    await processor_service.process_file(file_id)

    assert png.max_active_seen == 2, (
        f"Expected 2 pages in parallel, saw {png.max_active_seen}"
    )


async def test_gemini_concurrency_limit() -> None:
    max_concurrency = 2

    active_calls = 0
    max_active_seen = 0

    class SlowOcrModel(FakeOcrModel):
        async def extract_text(self, png_data: bytes, prompt: str) -> str:
            nonlocal active_calls, max_active_seen
            active_calls += 1
            max_active_seen = max(max_active_seen, active_calls)
            try:
                await asyncio.sleep(0.1)
                return await super().extract_text(png_data, prompt)
            finally:
                active_calls -= 1

    model = ConcurrencyLimitedOcrModel(SlowOcrModel(), max_concurrency=max_concurrency)
    tasks = [model.extract_text(b"png", "prompt") for _ in range(4)]
    await asyncio.gather(*tasks)

    assert max_active_seen == 2, (
        f"Expected max 2 concurrent calls, saw {max_active_seen}"
    )
    assert active_calls == 0


async def test_processor_pause_resume(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    summary_service: SummaryService,
) -> None:
    coordination_service = SqliteCoordinationService(session_manager)

    processor_service = ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
        coordination_service=coordination_service,
        concurrency=1,
    )

    # 1. Default state
    assert processor_service.is_processing_enabled() is True

    # 2. Pause
    await processor_service.pause()
    assert processor_service.is_processing_enabled() is False
    assert await coordination_service.get_value("queue_paused") == "true"

    # Start service in paused state
    hashing = SlowModule("Hashing", 0.0)
    processor_service.register_modules(hashing=hashing, png=None)

    # Start the workers (they will be blocked since it's paused)
    for i in range(processor_service.concurrency):
        worker = asyncio.create_task(processor_service.worker_loop(i))
        processor_service.workers.append(worker)

    # Enqueue file ID
    await processor_service.queue.put(101)
    await asyncio.sleep(0.1)

    # Module should NOT have been called while paused
    assert hashing.calls == []

    # 3. Resume
    await processor_service.resume()
    assert processor_service.is_processing_enabled() is True
    assert await coordination_service.get_value("queue_paused") == "false"

    # Wait for the worker to process the item
    await asyncio.sleep(0.1)

    # Module should now have been called for file 101
    assert hashing.calls == [(101, None, None)]

    # Cleanup
    await processor_service.stop()


async def test_process_file_without_page_modules(
    processor_service: ProcessorService,
) -> None:
    """Verify process_file runs global pre-modules and skips page queries when no page_modules are registered."""
    hashing = SlowModule("Hashing", 0.0)

    processor_service.register_modules(hashing=hashing, png=None)
    assert processor_service.page_modules == []
    assert processor_service.global_post_modules == []

    await processor_service.process_file(123)
    assert hashing.calls == [(123, None, None)]


async def test_process_file_publishes_processing_completed_event(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify process_file publishes NoteProcessingCompletedEvent when pipeline completes."""
    file_id = 777
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=10,
                user_id=7,
                file_name="Note",
                directory_id=0,
                is_folder="Y",
            )
        )
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                file_name="Daily.note",
                directory_id=10,
                storage_key="key",
                md5="hash",
            )
        )
        await session.commit()

    hashing = SlowModule("Hashing", 0.0)
    processor_service.register_modules(hashing=hashing, png=None)

    received_events: list[Event] = []

    async def capture_event(event: Event) -> None:
        received_events.append(event)

    processor_service.event_bus.subscribe(NoteProcessingCompletedEvent, capture_event)

    await processor_service.process_file(file_id)
    for _ in range(10):
        await asyncio.sleep(0)

    assert received_events == [
        NoteProcessingCompletedEvent(
            file_id=file_id,
            user_id=7,
            file_path="Note/Daily.note",
        )
    ]


async def test_recover_missing_tasks_skips_inactive_files(
    session_manager: DatabaseSessionManager,
    processor_service: ProcessorService,
) -> None:
    """Verify recover_missing_tasks enqueues active .note files and ignores inactive files."""
    async with session_manager.session() as session:
        # Active note with missing tasks
        session.add(
            UserFileDO(
                id=9001,
                user_id=1,
                file_name="active.note",
                storage_key="k1",
                md5="m1",
                is_active="Y",
            )
        )
        # Soft-deleted note (in recycle bin)
        session.add(
            UserFileDO(
                id=9002,
                user_id=1,
                file_name="deleted.note",
                storage_key="k2",
                md5="m2",
                is_active="N",
            )
        )
        await session.commit()

    await processor_service.recover_missing_tasks()

    assert 9001 in processor_service.processing_files
    assert 9002 not in processor_service.processing_files
    assert processor_service.queue.qsize() == 1
    enqueued = await processor_service.queue.get()
    assert enqueued == 9001


async def test_recover_missing_tasks_backfills_embedding_model_and_ai_modules(
    session_manager: DatabaseSessionManager,
    processor_service: ProcessorService,
    file_service: FileService,
    summary_service: SummaryService,
) -> None:
    """Verify recover_missing_tasks enqueues files needing OCR, embedding, or summary backfill."""
    processor_service.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        png=None,
        ocr=OcrModule(file_service=file_service, ocr_model=FakeOcrModel()),
        embedding=EmbeddingModule(
            file_service=file_service,
            embedding_model=FakeEmbeddingModel(model_id="new-model"),
        ),
        summary=SummaryModule(
            file_service=file_service,
            summary_service=summary_service,
            summary_model=FakeSummaryModel(),
        ),
    )

    async with session_manager.session() as session:
        # File 9101: All tasks completed with current model ("new-model") -> should NOT be enqueued
        # File 9102: Missing OCR_EXTRACTION task -> needs OCR backfill
        # File 9103: Has EMBEDDING_GENERATION with data="old-model" -> needs embedding backfill
        # File 9104: Missing SUMMARY_GENERATION task -> needs summary backfill
        # File 9105: Legacy HASHING task with data=None -> needs metadata/ink backfill
        for fid in (9101, 9102, 9103, 9104, 9105):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=1,
                    file_name=f"f{fid}.note",
                    storage_key=f"k{fid}",
                    md5="m",
                    is_active="Y",
                )
            )
            session.add(
                NotePageContentDO(
                    file_id=fid,
                    page_index=0,
                    page_id="p0",
                    content_hash="h",
                )
            )
            session.add(
                SystemTaskDO(
                    file_id=fid,
                    task_type="HASHING",
                    key="global",
                    status="COMPLETED",
                    data=None if fid == 9105 else "v2",
                )
            )

        session.add_all(
            [
                # 9101: Complete for OCR, EMBEDDING ("new-model"), and SUMMARY
                SystemTaskDO(
                    file_id=9101,
                    task_type="OCR_EXTRACTION",
                    key="page_p0",
                    status="COMPLETED",
                ),
                SystemTaskDO(
                    file_id=9101,
                    task_type="EMBEDDING_GENERATION",
                    key="page_p0",
                    status="COMPLETED",
                    data="new-model",
                ),
                SystemTaskDO(
                    file_id=9101,
                    task_type="SUMMARY_GENERATION",
                    key="global",
                    status="COMPLETED",
                ),
                # 9102: Missing OCR_EXTRACTION (and EMBEDDING_GENERATION)
                SystemTaskDO(
                    file_id=9102,
                    task_type="SUMMARY_GENERATION",
                    key="global",
                    status="COMPLETED",
                ),
                # 9103: EMBEDDING_GENERATION completed with old-model
                SystemTaskDO(
                    file_id=9103,
                    task_type="OCR_EXTRACTION",
                    key="page_p0",
                    status="COMPLETED",
                ),
                SystemTaskDO(
                    file_id=9103,
                    task_type="EMBEDDING_GENERATION",
                    key="page_p0",
                    status="COMPLETED",
                    data="old-model",
                ),
                SystemTaskDO(
                    file_id=9103,
                    task_type="SUMMARY_GENERATION",
                    key="global",
                    status="COMPLETED",
                ),
                # 9104: Missing SUMMARY_GENERATION
                SystemTaskDO(
                    file_id=9104,
                    task_type="OCR_EXTRACTION",
                    key="page_p0",
                    status="COMPLETED",
                ),
                SystemTaskDO(
                    file_id=9104,
                    task_type="EMBEDDING_GENERATION",
                    key="page_p0",
                    status="COMPLETED",
                    data="new-model",
                ),
                # 9105: Complete downstream tasks, but legacy HASHING data=None
                SystemTaskDO(
                    file_id=9105,
                    task_type="OCR_EXTRACTION",
                    key="page_p0",
                    status="COMPLETED",
                ),
                SystemTaskDO(
                    file_id=9105,
                    task_type="EMBEDDING_GENERATION",
                    key="page_p0",
                    status="COMPLETED",
                    data="new-model",
                ),
                SystemTaskDO(
                    file_id=9105,
                    task_type="SUMMARY_GENERATION",
                    key="global",
                    status="COMPLETED",
                ),
            ]
        )
        await session.commit()

    await processor_service.recover_missing_tasks()

    assert 9101 not in processor_service.processing_files
    assert {9102, 9103, 9104, 9105}.issubset(processor_service.processing_files)


async def test_sync_completed_event_enqueues_new_and_updated_notes(
    session_manager: DatabaseSessionManager,
    processor_service: ProcessorService,
    file_service: FileService,
    blob_storage: BlobStorage,
    test_user_id: int,
) -> None:
    """Verify SyncCompletedEvent enqueues new notes and notes whose HASHING checkpoint was invalidated on overwrite."""
    processor_service.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        png=None,
    )

    await blob_storage.put(USER_DATA_BUCKET, "k_old", b"old-content")
    await blob_storage.put(USER_DATA_BUCKET, "k_new", b"new-content")
    old_md5 = hashlib.md5(b"old-content").hexdigest()
    new_md5 = hashlib.md5(b"new-content").hexdigest()

    # Upload initial note and mark its HASHING checkpoint COMPLETED
    entity = await file_service.finish_upload(
        "test@example.com", "updated.note", "/Note", old_md5, inner_name="k_old"
    )
    async with session_manager.session() as session:
        session.add_all(
            [
                SystemTaskDO(
                    file_id=entity.id,
                    task_type=TaskType.PAGE_HASHING,
                    key="global",
                    status="COMPLETED",
                    data="v2",
                ),
                # Up-to-date note -> skip
                UserFileDO(
                    id=9201,
                    user_id=test_user_id,
                    file_name="unchanged.note",
                    storage_key="k9201",
                    md5="m1",
                    is_active="Y",
                ),
                SystemTaskDO(
                    file_id=9201,
                    task_type=TaskType.PAGE_HASHING,
                    key="global",
                    status="COMPLETED",
                    data="v2",
                ),
                # Brand-new note for test_user_id (no tasks yet) -> enqueue
                UserFileDO(
                    id=9203,
                    user_id=test_user_id,
                    file_name="new.note",
                    storage_key="k9203",
                    md5="m3",
                    is_active="Y",
                ),
                # Unprocessed note belonging to another user -> skip
                UserFileDO(
                    id=9204,
                    user_id=test_user_id + 999,
                    file_name="other_user.note",
                    storage_key="k9204",
                    md5="m4",
                    is_active="Y",
                ),
            ]
        )
        await session.commit()

    # Subscribe processor_service to file_service's event_bus and overwrite updated.note:
    # finish_upload publishes NoteUpdatedEvent(defer_processing=True), which invalidates
    # the PAGE_HASHING checkpoint without enqueueing the file until SyncCompletedEvent.
    assert file_service.event_bus is not None
    file_service.event_bus.subscribe(
        NoteUpdatedEvent, processor_service.handle_note_updated
    )
    await file_service.finish_upload(
        "test@example.com", "updated.note", "/Note", new_md5, inner_name="k_new"
    )
    await asyncio.sleep(0.05)
    assert entity.id not in processor_service.processing_files

    await processor_service.handle_sync_completed(
        SyncCompletedEvent(user_id=test_user_id)
    )

    assert 9201 not in processor_service.processing_files
    assert 9204 not in processor_service.processing_files
    assert {entity.id, 9203}.issubset(processor_service.processing_files)


async def test_get_file_processing_statuses(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify batched file processing status aggregation, ownership scoping, and queue overrides."""
    assert await processor_service.get_file_processing_statuses(test_user_id, []) == {}

    other_user_id = test_user_id + 999
    async with session_manager.session() as session:
        for fid in (10, 20, 30, 40, 60):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=test_user_id,
                    file_name=f"Note{fid}.note",
                    directory_id=0,
                )
            )
        session.add(
            UserFileDO(
                id=77,
                user_id=other_user_id,
                file_name="OtherUser.note",
                directory_id=0,
            )
        )
        session.add_all(
            [
                SystemTaskDO(file_id=10, task_type="PNG", key="p0", status="FAILED"),
                SystemTaskDO(file_id=10, task_type="OCR", key="p0", status="COMPLETED"),
                SystemTaskDO(
                    file_id=20, task_type="PNG", key="p0", status="PROCESSING"
                ),
                SystemTaskDO(file_id=30, task_type="PNG", key="p0", status="COMPLETED"),
                SystemTaskDO(file_id=40, task_type="PNG", key="p0", status="PENDING"),
                SystemTaskDO(file_id=77, task_type="PNG", key="p0", status="FAILED"),
            ]
        )
        await session.commit()

    statuses = await processor_service.get_file_processing_statuses(
        user_id=test_user_id,
        file_ids=[10, 20, 30, 40, 50, 60, 77],
    )
    assert statuses == {
        10: ProcessingStatus.FAILED,
        20: ProcessingStatus.PROCESSING,
        30: ProcessingStatus.COMPLETED,
        40: ProcessingStatus.PENDING,
        50: ProcessingStatus.NONE,
        60: ProcessingStatus.NONE,
        77: ProcessingStatus.NONE,
    }

    # Enqueue files via the public NoteUpdatedEvent handler (workers not started):
    # - 60 has no SystemTaskDO rows yet -> PENDING
    # - 30 was previously COMPLETED and is now re-queued -> PENDING
    # - 20 already has an active PROCESSING task -> PROCESSING
    for fid in (20, 30, 60):
        await processor_service.handle_note_updated(
            NoteUpdatedEvent(
                file_id=fid,
                user_id=test_user_id,
                file_path=f"/Note/Note{fid}.note",
            )
        )

    queued_statuses = await processor_service.get_file_processing_statuses(
        user_id=test_user_id,
        file_ids=[20, 30, 60],
    )
    assert queued_statuses == {
        20: ProcessingStatus.PROCESSING,
        30: ProcessingStatus.PENDING,
        60: ProcessingStatus.PENDING,
    }


async def test_get_note_and_page_metadata(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    file_service: FileService,
    test_user_id: int,
) -> None:
    """Verify get_note_metadata and get_note_page_metadata return separated notebook/page metadata and enforce ownership."""
    hashing = PageHashingModule(file_service=file_service)

    # Legacy pre-PAGEID note with keywords + titles (philips/test.note),
    # modern note with links (A5X_TestNote_Links.note), and mixed ink/blank note
    test_note = Path("tests/testdata/philips/test.note")
    links_note = Path("tests/testdata/nelinory/A5X_TestNote_Links.note")
    mixed_note = Path("tests/testdata/nelinory/A5X_TestNote_With_Pdf_Template.note")
    await blob_storage.put(USER_DATA_BUCKET, "meta_test_key", test_note.read_bytes())
    await blob_storage.put(USER_DATA_BUCKET, "meta_links_key", links_note.read_bytes())
    await blob_storage.put(USER_DATA_BUCKET, "meta_mixed_key", mixed_note.read_bytes())

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=501,
                    user_id=test_user_id,
                    file_name="Structured.note",
                    storage_key="meta_test_key",
                    directory_id=0,
                    is_active="Y",
                ),
                UserFileDO(
                    id=502,
                    user_id=test_user_id,
                    file_name="Links.note",
                    storage_key="meta_links_key",
                    directory_id=0,
                    is_active="Y",
                ),
                UserFileDO(
                    id=503,
                    user_id=test_user_id,
                    file_name="Unindexed.note",
                    storage_key="unindexed_key",
                    directory_id=0,
                    is_active="Y",
                ),
                UserFileDO(
                    id=504,
                    user_id=test_user_id,
                    file_name="CorruptMeta.note",
                    storage_key="corrupt_meta_key",
                    directory_id=0,
                    is_active="Y",
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=504,
                    file_type="note",
                    total_pages=1,
                    header_json="not-json",
                    footer_json="{}",
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=504,
                    page_index=0,
                    page_id="p0",
                    page_json="not-json",
                ),
                UserFileDO(
                    id=507,
                    user_id=test_user_id,
                    file_name="ListHeader.note",
                    storage_key="list_header_key",
                    directory_id=0,
                    is_active="Y",
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=507,
                    file_type="note",
                    total_pages=1,
                    header_json="[]",
                    footer_json="{}",
                ),
                UserFileDO(
                    id=505,
                    user_id=test_user_id,
                    file_name="Mixed.note",
                    storage_key="meta_mixed_key",
                    directory_id=0,
                    is_active="Y",
                ),
            ]
        )
        await session.commit()

    assert await hashing.run(501, session_manager) is True
    assert await hashing.run(502, session_manager) is True
    assert await hashing.run(505, session_manager) is True

    # Missing file, unauthorized user, unindexed file, corrupt metadata -> None
    assert await processor_service.get_note_metadata(test_user_id, 99999) is None
    assert await processor_service.get_note_metadata(test_user_id + 1, 501) is None
    assert await processor_service.get_note_metadata(test_user_id, 503) is None
    assert await processor_service.get_note_metadata(test_user_id, 504) is None
    assert await processor_service.get_note_metadata(test_user_id, 507) is None

    assert await processor_service.get_note_page_metadata(test_user_id, 99999) is None
    assert await processor_service.get_note_page_metadata(test_user_id + 1, 501) is None
    assert await processor_service.get_note_page_metadata(test_user_id, 503) is None

    # Corrupt page_json gracefully falls back to five_star == []
    corrupt_pages = await processor_service.get_note_page_metadata(test_user_id, 504)
    assert corrupt_pages is not None
    assert corrupt_pages.pages[0].five_star == []

    # Legacy pre-PAGEID note (501) gets concrete True booleans on NotePageMetadataDO!
    vo_501 = await processor_service.get_note_metadata(test_user_id, 501)
    assert vo_501 is not None
    assert vo_501.file_id == 501
    assert vo_501.file_type == "note"
    assert vo_501.total_pages == 2
    assert len(vo_501.keywords) == 2
    assert len(vo_501.titles) == 2

    pages_501 = await processor_service.get_note_page_metadata(test_user_id, 501)
    assert pages_501 is not None
    assert len(pages_501.pages) == 2
    assert pages_501.pages[0].has_ink is True
    assert pages_501.pages[0].has_drawables is True
    assert pages_501.pages[0].has_content is True
    assert pages_501.pages[0].style_label == "8mm Ruled Line"

    vo_502 = await processor_service.get_note_metadata(test_user_id, 502)
    assert vo_502 is not None
    assert len(vo_502.links) == 8
    assert any(lk.target is not None for lk in vo_502.links)

    pages_502 = await processor_service.get_note_page_metadata(test_user_id, 502)
    assert pages_502 is not None
    assert pages_502.pages[0].has_ink is True
    assert pages_502.pages[0].has_drawables is True
    assert pages_502.pages[0].has_content is True
    assert len(pages_502.pages[0].links) > 0

    pages_505 = await processor_service.get_note_page_metadata(test_user_id, 505)
    assert pages_505 is not None
    assert [p.has_ink for p in pages_505.pages] == [True, False, True]
    assert [p.has_drawables for p in pages_505.pages] == [True, False, True]
    assert [p.has_content for p in pages_505.pages] == [True, False, True]

    sliced_505 = await processor_service.get_note_page_metadata(
        test_user_id, 505, start_index=1, end_index=2
    )
    assert sliced_505 is not None
    assert sliced_505.total_pages == 3
    assert [p.page_index for p in sliced_505.pages] == [1, 2]


async def test_process_file_serializes_same_file_concurrency(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    file_service: FileService,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify concurrent process_file calls for the same file_id serialize cleanly without lock leaks."""
    await blob_storage.put(
        USER_DATA_BUCKET, "concurrent_hash_key", test_note_path.read_bytes()
    )
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=506,
                user_id=test_user_id,
                file_name="Concurrent.note",
                storage_key="concurrent_hash_key",
                directory_id=0,
                is_active="Y",
            )
        )
        await session.commit()

    processor_service.register_modules(hashing=PageHashingModule(file_service))
    results = await asyncio.gather(
        processor_service.process_file(506),
        processor_service.process_file(506, task_types={TaskType.PAGE_HASHING}),
    )
    assert results == [True, True]
    assert processor_service._file_locks == {}
