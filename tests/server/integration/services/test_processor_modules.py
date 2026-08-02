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


async def test_explicit_orchestration_flow(
    processor_service: ProcessorService,
) -> None:
    # Setup - Create Mocks explicitly
    hashing = MagicMock(spec=PageHashingModule)
    hashing.run = AsyncMock(return_value=True)

    png = MagicMock(spec=PngConversionModule)
    png.run = AsyncMock(return_value=True)

    ocr = MagicMock(spec=GeminiOcrModule)
    ocr.run = AsyncMock(return_value=True)

    embedding = MagicMock(spec=GeminiEmbeddingModule)
    embedding.run = AsyncMock(return_value=True)

    summary = MagicMock(spec=SummaryModule)
    summary.run = AsyncMock(return_value=True)

    # Register
    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    # Mock DB Session (2 pages)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(0, "p0"), (1, "p1")]
    mock_session.execute.return_value = mock_result

    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # Execute
    file_id = 123
    await processor_service.process_file(file_id)

    # Verify flow
    hashing.run.assert_called_once_with(file_id, sm_mock)

    # Per-Page Pipeline (Parallel across pages)
    png.run.assert_any_call(file_id, sm_mock, page_index=0, page_id="p0")
    png.run.assert_any_call(file_id, sm_mock, page_index=1, page_id="p1")
    ocr.run.assert_any_call(file_id, sm_mock, page_index=0, page_id="p0")
    embedding.run.assert_any_call(file_id, sm_mock, page_index=0, page_id="p0")

    # Summary (Global) runs last
    summary.run.assert_called_once_with(file_id, sm_mock)


async def test_dependant_skipping(
    processor_service: ProcessorService,
) -> None:
    """Verify that if a module fails (returns False), the page pipeline stops."""
    # Setup - Create Mocks explicitly
    hashing = MagicMock(spec=PageHashingModule)
    hashing.run = AsyncMock(return_value=True)

    # PNG returns FALSE -> Failure/Stall
    png = MagicMock(spec=PngConversionModule)
    png.run = AsyncMock(return_value=False)

    ocr = MagicMock(spec=GeminiOcrModule)
    ocr.run = AsyncMock(return_value=True)

    embedding = MagicMock(spec=GeminiEmbeddingModule)
    embedding.run = AsyncMock(return_value=True)

    summary = MagicMock(spec=SummaryModule)
    summary.run = AsyncMock(return_value=True)

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
    mock_result.all.return_value = [(0, "p0")]
    mock_session.execute.return_value = mock_result

    sm_mock = cast(MagicMock, processor_service.session_manager)
    sm_mock.session.return_value.__aenter__.return_value = mock_session

    # Execute
    file_id = 123
    await processor_service.process_file(file_id)

    # Verify
    png.run.assert_called_once_with(file_id, sm_mock, page_index=0, page_id="p0")

    # OCR and Embedding should NOT be checked because PNG returned False
    ocr.run.assert_not_called()
    embedding.run.assert_not_called()

    # Summary (Global) should still run
    summary.run.assert_called_once_with(file_id, sm_mock)
