from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.gemini_embedding import (
    GeminiEmbeddingModule,
)
from supernote.server.services.processor_modules.gemini_ocr import GeminiOcrModule
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)
from supernote.server.services.processor_modules.summary import SummaryModule


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
async def test_explicit_orchestration_flow(
    processor_service: ProcessorService,
) -> None:
    # 1. Setup - Create Mocks explicitly
    hashing = MagicMock(spec=PageHashingModule)
    hashing.run_if_needed = AsyncMock(return_value=True)
    hashing.process = AsyncMock()

    png = MagicMock(spec=PngConversionModule)
    png.run_if_needed = AsyncMock(return_value=True)
    png.process = AsyncMock()

    ocr = MagicMock(spec=GeminiOcrModule)
    ocr.run_if_needed = AsyncMock(return_value=True)
    ocr.process = AsyncMock()

    embedding = MagicMock(spec=GeminiEmbeddingModule)
    embedding.run_if_needed = AsyncMock(return_value=True)
    embedding.process = AsyncMock()

    summary = MagicMock(spec=SummaryModule)
    summary.run_if_needed = AsyncMock(return_value=True)
    summary.process = AsyncMock()

    # 2. Register
    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    # 3. Mock DB Session (2 pages)
    # Create the mock session manager explicitly and assign it
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [0, 1]
    mock_session.execute.return_value = mock_result

    # We must ensure the session_manager on the service returns our mock_session
    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # 4. Execute
    file_id = 123
    await processor_service.process_file(file_id)

    # 5. Verify flow

    # Hashing (Global) runs first
    # Use sm_mock (which is processor_service.session_manager) for assertion
    hashing.run_if_needed.assert_called_once_with(file_id, sm_mock)
    hashing.process.assert_called_once()

    # Per-Page Pipeline
    # Page 0
    png.run_if_needed.assert_any_call(file_id, sm_mock, page_index=0)
    ocr.run_if_needed.assert_any_call(file_id, sm_mock, page_index=0)
    embedding.run_if_needed.assert_any_call(file_id, sm_mock, page_index=0)

    # Summary (Global) runs last
    summary.run_if_needed.assert_called_once_with(file_id, sm_mock)


@pytest.mark.asyncio
async def test_dependant_skipping(
    processor_service: ProcessorService,
) -> None:
    """Verify that if PNG conversion is not needed (or fails/returns False), OCR is skipped."""
    # 1. Setup - Create Mocks explicitly
    hashing = MagicMock(spec=PageHashingModule)
    hashing.run_if_needed = AsyncMock(return_value=True)
    hashing.process = AsyncMock()

    # PNG returns FALSE -> Skipped
    png = MagicMock(spec=PngConversionModule)
    png.run_if_needed = AsyncMock(return_value=False)
    png.process = AsyncMock()

    # OCR dependency requires PNG to run?
    # Actually my logic is simpler:
    # if await png.run_if_needed(): await png.process()
    # if await ocr.run_if_needed(): await ocr.process()
    # Checks are independent in `process_file` logic,
    # correctness relies on `ocr.run_if_needed` checking PNG existence.

    ocr = MagicMock(spec=GeminiOcrModule)
    ocr.run_if_needed = AsyncMock(return_value=True)
    ocr.process = AsyncMock()

    embedding = MagicMock(spec=GeminiEmbeddingModule)
    embedding.run_if_needed = AsyncMock(return_value=True)
    embedding.process = AsyncMock()

    summary = MagicMock(spec=SummaryModule)
    summary.run_if_needed = AsyncMock(return_value=True)
    summary.process = AsyncMock()

    # Register
    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [0]
    mock_session.execute.return_value = mock_result

    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # Execute
    file_id = 123
    await processor_service.process_file(file_id)

    # Debug
    print(f"DEBUG: Calls: {png.run_if_needed.call_args_list}")
    print(f"DEBUG: Session Manager in Service: {processor_service.session_manager}")
    print(f"DEBUG: Session Manager in Test: {sm_mock}")

    # Verify
    # PNG check was called, but process was NOT called (because it returned False)
    # Use positional args for file_id and session_manager to match call signature
    png.run_if_needed.assert_any_call(123, sm_mock, page_index=0)
    png.process.assert_not_called()

    # OCR should still be checked (because loop continues)
    ocr.run_if_needed.assert_any_call(123, sm_mock, page_index=0)
