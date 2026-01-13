from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules import ProcessorModule


class MockModule(ProcessorModule):
    def __init__(self, name: str, should_run: bool = True) -> None:
        self._name = name
        self.should_run = should_run
        self.process_called = False
        self.process_args: tuple[int, int | None] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_type(self) -> str:
        return "MOCK"

    async def should_process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
    ) -> bool:
        return self.should_run

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        **kwargs: object,
    ) -> None:
        self.process_called = True
        self.process_args = (file_id, page_index)


@pytest.fixture
def processor_service() -> ProcessorService:
    service = ProcessorService(
        event_bus=MagicMock(),
        session_manager=MagicMock(),
        file_service=MagicMock(),
        summary_service=MagicMock(),
    )
    return service


@pytest.mark.asyncio
async def test_processor_runs_global_modules(
    processor_service: ProcessorService,
) -> None:
    # Setup
    module1 = MockModule("Module1")
    processor_service.register_module(module1)

    # Mock finding 0 pages so only global modules run
    # We mock session.execute to return empty list for pages
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = []
    mock_session.execute.return_value = mock_result

    # Cast/ignore to suppress MyPy complaining about MagicMock attributes on real type
    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # Execute
    await processor_service.process_file(123)

    # Verify
    assert module1.process_called
    assert module1.process_args == (123, None)


@pytest.mark.asyncio
async def test_processor_runs_page_modules(processor_service: ProcessorService) -> None:
    # Setup
    module1 = MockModule("Module1")
    processor_service.register_module(module1)

    # Mock finding 2 pages (index 0 and 1)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [0, 1]
    mock_session.execute.return_value = mock_result

    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # Execute
    await processor_service.process_file(123)

    # Verify
    # Module1 should run globally (None) AND for each page (0, 1) if logic allows
    # Wait, my logic currently iterates ALL modules for Global, then ALL modules for Pages.
    # If should_process returns True for page_index=None, it runs globally.
    # If should_process returns True for page_index=0, it runs for page 0.
    # My MockModule returns True always.

    # But since I'm reusing the module instance, I can't easily track multiple calls with just a bool flag.
    # Let's use MagicMock for process method on the module instance to track calls.
    with patch.object(module1, "process", new_callable=AsyncMock) as mock_process:
        await processor_service.process_file(123)

        assert mock_process.call_count == 3  # 1 global + 2 pages

        # Verify calls
        # Call 1: Global
        mock_process.assert_any_call(
            123, processor_service.session_manager, page_index=None
        )
        # Call 2: Page 0
        mock_process.assert_any_call(
            123, processor_service.session_manager, page_index=0
        )
        # Call 3: Page 1
        mock_process.assert_any_call(
            123, processor_service.session_manager, page_index=1
        )
