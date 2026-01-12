import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.services.processor import ProcessorService


@pytest.fixture(name="processor_service")
def processor_service_fixture() -> ProcessorService:
    return ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=MagicMock(),
        file_service=MagicMock(),
        summary_service=MagicMock(),
    )


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
