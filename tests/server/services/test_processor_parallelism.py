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
        self.active_count = 0
        self.max_active_seen = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_type(self) -> str:
        return "SLOW_TASK"

    async def run_if_needed(self, *args, **kwargs) -> bool:
        return True

    async def process(self, *args, **kwargs) -> None:
        self.active_count += 1
        self.max_active_seen = max(self.max_active_seen, self.active_count)
        try:
            await asyncio.sleep(self.sleep_time)
        finally:
            self.active_count -= 1


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
    png = SlowModule("PNG", 0.1)
    # Global post-module (Summary) - fast
    summary = SlowModule("Summary", 0.01)

    service.register_modules(
        hashing=hashing,
        png=png,
        ocr=MagicMock(spec=ProcessorModule),
        embedding=MagicMock(spec=ProcessorModule),
        summary=summary,
    )
    # Override standard page modules for this test
    service.page_modules = [png]

    # Mock 4 pages
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [0, 1, 2, 3]
    mock_session.execute.return_value = mock_result
    service.session_manager.session.return_value.__aenter__.return_value = mock_session

    await service.process_file(123)

    # Verify parallelism: max_active_seen should be 4
    assert png.max_active_seen == 4, f"Expected 4 pages in parallel, saw {png.max_active_seen}"


@pytest.mark.asyncio
async def test_gemini_concurrency_limit() -> None:
    # Set limit to 2
    max_concurrency = 2
    from supernote.server.services.gemini import GeminiService
    service = GeminiService(api_key="fake-key", max_concurrency=max_concurrency)
    
    # Mock the client
    mock_client = MagicMock()
    service._client = mock_client
    
    active_calls = 0
    max_active_seen = 0
    
    # Create a mock method that tracks concurrency
    async def slow_call(*args, **kwargs):
        nonlocal active_calls, max_active_seen
        active_calls += 1
        max_active_seen = max(max_active_seen, active_calls)
        try:
            await asyncio.sleep(0.1)
            return MagicMock()
        finally:
            active_calls -= 1

    mock_client.aio.models.generate_content = AsyncMock(side_effect=slow_call)
    
    # Run 4 calls. With limit 2, max_active_seen should NEVER exceed 2.
    tasks = [
        service.generate_content("model", "content")
        for _ in range(4)
    ]
    await asyncio.gather(*tasks)
    
    # Verify concurrency limit: max_active_seen should be exactly 2
    assert max_active_seen == 2, f"Expected max 2 concurrent calls, saw {max_active_seen}"
    assert active_calls == 0


@pytest.mark.asyncio
async def test_gemini_semaphore_lazy_init() -> None:
    from supernote.server.services.gemini import GeminiService
    service = GeminiService(api_key="fake-key", max_concurrency=5)
    assert service._semaphore is None
    
    sem = service._get_semaphore()
    assert sem is not None
    assert isinstance(sem, asyncio.Semaphore)
    assert service._semaphore is sem
    assert sem._value == 5
