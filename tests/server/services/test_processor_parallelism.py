import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules import ProcessorModule


class SlowModule(ProcessorModule):
    def __init__(self, name: str, sleep_time: float):
        self._name = name
        self.sleep_time = sleep_time

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_type(self) -> str:
        return "SLOW_TASK"

    async def run_if_needed(self, *args, **kwargs) -> bool:
        return True

    async def process(self, *args, **kwargs) -> None:
        await asyncio.sleep(self.sleep_time)


@pytest.mark.asyncio
async def test_page_parallelism() -> None:
    # Setup service
    service = ProcessorService(
        event_bus=MagicMock(),
        session_manager=MagicMock(),
        file_service=MagicMock(),
        summary_service=MagicMock(),
    )

    # Global pre-module (Hashing) - fast
    hashing = SlowModule("Hashing", 0.01)
    # Page module - slow
    png = SlowModule("PNG", 0.5)
    # Global post-module (Summary) - fast
    summary = SlowModule("Summary", 0.01)

    service.register_modules(
        hashing=hashing,
        png=png,
        ocr=MagicMock(spec=ProcessorModule), # won't be called if we don't return success? 
        # Actually register_modules sets page_modules
        embedding=MagicMock(spec=ProcessorModule),
        summary=summary
    )
    # Override standard page modules for this test
    service.page_modules = [png]

    # Mock 4 pages
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [0, 1, 2, 3]
    mock_session.execute.return_value = mock_result
    service.session_manager.session.return_value.__aenter__.return_value = mock_session

    start_time = time.perf_counter()
    await service.process_file(123)
    end_time = time.perf_counter()

    duration = end_time - start_time
    
    # If sequential: 0.01 (hashing) + 4 * 0.5 (png) + 0.01 (summary) = 2.02s
    # If parallel: 0.01 (hashing) + 0.5 (png) + 0.01 (summary) = ~0.52s
    
    print(f"DEBUG: Processing duration: {duration:.4f}s")
    assert duration < 1.0, f"Processing took too long ({duration:.4f}s), parallelism might be broken"
    assert duration >= 0.5, "Processing was too fast, did it actually run?"
