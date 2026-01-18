import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteDeletedEvent, NoteUpdatedEvent
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def mock_file_service() -> MagicMock:
    service = MagicMock()
    service.blob_storage = MagicMock()
    service.blob_storage.delete = AsyncMock()
    service.blob_storage.exists = AsyncMock()
    return service


@pytest.fixture(name="processor_service")
def processor_service_fixture(
    session_manager: DatabaseSessionManager, mock_file_service: MagicMock
) -> ProcessorService:
    return ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=mock_file_service,
        summary_service=MagicMock(),
    )


class SlowModule(ProcessorModule):
    def __init__(self, name: str, sleep_time: float):
        self._name = name
        self.sleep_time = sleep_time
        self.active_count = 0
        self.max_active_seen = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_type(self) -> str:
        return "SLOW_TASK"

    async def run_if_needed(self, *args: object, **kwargs: object) -> bool:
        return True

    async def process(self, *args: object, **kwargs: object) -> None:
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
    await processor_service.start()

    # Spy on handle_note_updated
    # We can't easily spy on the bound method directly because it's already subscribed
    # But we can verify side effects, e.g., the item in queue.

    event = NoteUpdatedEvent(file_id=123, user_id=1, file_path="test.note")
    await processor_service.event_bus.publish(event)

    # Wait briefly for async processing
    await asyncio.sleep(0.1)

    # Check if item was enqueued (it gets popped by worker immediately, so checking processing_files is unreliable if efficient)
    # However, since we didn't mock process_file, it will just log and finish.
    # Let's mock process_file to verify it was called.

    # To do this effectively, we should have mocked process_file BEFORE start() if we want to spy on it easily,
    # or rely on log capture.
    # Alternatively, we can inspect the queue size BUT workers consume it.

    # Let's verify via side effect: process_file should have been called.
    with patch.object(
        processor_service, "process_file", new_callable=AsyncMock
    ) as mock_process:
        # Publish again
        await processor_service.event_bus.publish(event)
        await asyncio.sleep(0.1)

        mock_process.assert_called_with(123)

    await processor_service.stop()


async def test_processor_deduplication(processor_service: ProcessorService) -> None:
    processor_service.queue = AsyncMock()  # Mock queue to prevent actual logic

    event = NoteUpdatedEvent(file_id=123, user_id=1, file_path="test.note")

    await processor_service.handle_note_updated(event)
    assert 123 in processor_service.processing_files
    processor_service.queue.put.assert_called_once_with(123)

    # Second event for same file should be ignored
    await processor_service.handle_note_updated(event)
    assert processor_service.queue.put.call_count == 1


async def test_handle_note_deleted_cleanup(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    mock_file_service: MagicMock,
) -> None:
    file_id = 999

    # Setup mock data in DB
    async with session_manager.session() as session:
        session.add(
            NotePageContentDO(
                file_id=file_id, page_index=0, page_id="p0", content_hash="h1"
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id, page_index=1, page_id="p1", content_hash="h2"
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

    # Trigger deletion event
    event = NoteDeletedEvent(file_id=file_id, user_id=1)
    await processor_service.handle_note_deleted(event)

    # Verify DB records are gone
    async with session_manager.session() as session:
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
        assert len(contents) == 0
        assert len(tasks) == 0

    # Verify Blobs are deleted
    mock_file_service.blob_storage.delete.assert_any_call(
        CACHE_BUCKET, get_page_png_path(file_id, "p0")
    )
    mock_file_service.blob_storage.delete.assert_any_call(
        CACHE_BUCKET, get_page_png_path(file_id, "p1")
    )


async def test_page_hashing_orphan_cleanup(
    session_manager: DatabaseSessionManager, mock_file_service: MagicMock
) -> None:
    file_id = 888
    hashing_module = PageHashingModule(file_service=mock_file_service)
    current_content_hash = get_md5_hash("page_content_0")

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
        for i in range(3):
            session.add(
                NotePageContentDO(
                    file_id=file_id,
                    page_index=i,
                    page_id=str(i),
                    content_hash=current_content_hash if i == 0 else f"old_{i}",
                )
            )
            session.add(
                SystemTaskDO(
                    file_id=file_id,
                    task_type="PNG_CONVERSION",
                    key=f"page_{i}",
                    status="COMPLETED",
                )
            )
        await session.commit()

    mock_metadata = MagicMock()
    mock_metadata.get_total_pages.return_value = 1
    mock_page = MagicMock()
    mock_page.__str__.return_value = "page_content_0"  # type: ignore[attr-defined]
    mock_page.get.return_value = "0"  # Matches existing page_id "0"
    mock_metadata.pages = [mock_page]
    mock_file_service.blob_storage.get_blob_path.return_value = MagicMock(
        exists=lambda: True
    )

    with patch(
        "supernote.server.services.processor_modules.page_hashing.parse_metadata",
        return_value=mock_metadata,
    ):
        with patch(
            "supernote.server.services.processor_modules.page_hashing._parse_helper",
            return_value=mock_metadata,
        ):
            await hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
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
        assert len(contents) == 1
        assert contents[0].page_index == 0

        stmt = select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
        tasks = (await session.execute(stmt)).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].key == "page_0"

    mock_file_service.blob_storage.delete.assert_any_call(
        CACHE_BUCKET, get_page_png_path(file_id, "1")
    )
    mock_file_service.blob_storage.delete.assert_any_call(
        CACHE_BUCKET, get_page_png_path(file_id, "2")
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


async def test_start_calls_recover_tasks(processor_service: ProcessorService) -> None:
    with patch.object(
        processor_service, "recover_tasks", new_callable=AsyncMock
    ) as mock_recover:
        with patch.object(processor_service, "worker_loop", return_value=AsyncMock()):
            await processor_service.start()
            await asyncio.sleep(0.01)
            mock_recover.assert_called_once()
            await processor_service.stop()


async def test_page_parallelism(
    processor_service: ProcessorService, session_manager: DatabaseSessionManager
) -> None:
    hashing = SlowModule("Hashing", 0.01)
    png = SlowModule("PNG", 0.1)
    summary = SlowModule("Summary", 0.01)

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=MagicMock(spec=ProcessorModule),
        embedding=MagicMock(spec=ProcessorModule),
        summary=summary,
    )
    processor_service.page_modules = [png]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    # Mock return must now match (page_index, page_id) tuple structure
    mock_result.all.return_value = [
        (0, "p0"),
        (1, "p1"),
        (2, "p2"),
        (3, "p3"),
    ]
    mock_session.execute.return_value = mock_result
    # Use patch.object to mock the session context manager
    with patch.object(session_manager, "session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__.return_value = mock_session
        await processor_service.process_file(123)

    assert png.max_active_seen == 4, (
        f"Expected 4 pages in parallel, saw {png.max_active_seen}"
    )


async def test_gemini_concurrency_limit() -> None:
    max_concurrency = 2
    from supernote.server.services.gemini import GeminiService

    # Use patch to avoid actually calling the API
    with patch("google.genai.Client") as mock_client_cls:
        service = GeminiService(api_key="fake-key", max_concurrency=max_concurrency)
        mock_client = mock_client_cls.return_value
        service._client = mock_client

        active_calls = 0
        max_active_seen = 0

        async def slow_call(*args: object, **kwargs: object) -> MagicMock:
            nonlocal active_calls, max_active_seen
            active_calls += 1
            max_active_seen = max(max_active_seen, active_calls)
            try:
                await asyncio.sleep(0.1)
                return MagicMock()
            finally:
                active_calls -= 1

        mock_client.aio.models.generate_content = AsyncMock(side_effect=slow_call)

        tasks = [service.generate_content("model", "content") for _ in range(4)]
        await asyncio.gather(*tasks)

        assert max_active_seen == 2, (
            f"Expected max 2 concurrent calls, saw {max_active_seen}"
        )
        assert active_calls == 0
