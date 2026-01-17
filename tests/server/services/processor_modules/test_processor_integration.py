from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
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
def mock_summary_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def processor_service(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    mock_summary_service: MagicMock,
) -> ProcessorService:
    return ProcessorService(
        event_bus=MagicMock(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=mock_summary_service,
    )


@pytest.mark.asyncio
async def test_full_processing_pipeline_with_real_file(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
    server_config_gemini: MagicMock,
    mock_gemini_service: MagicMock,
) -> None:
    """Full integration test using a real .note file."""
    
    # Setup Data
    user_id = 100
    file_id = 999
    storage_key = "test_integration_note"
    
    if not test_note_path.exists():
        pytest.skip(f"Test file not found at {test_note_path}")
        
    file_content = test_note_path.read_bytes()
    await blob_storage.put(USER_DATA_BUCKET, storage_key, file_content)
    
    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)
        await session.commit()

    # Register real modules (mostly)
    hashing = PageHashingModule(processor_service.file_service)
    png = PngConversionModule(processor_service.file_service)
    # Mock Gemini modules because they need API keys
    ocr = GeminiOcrModule(
        processor_service.file_service, server_config_gemini, mock_gemini_service
    )
    embedding = GeminiEmbeddingModule(
        processor_service.file_service, server_config_gemini, mock_gemini_service
    )
    summary = SummaryModule()

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    # Mock Gemini responses
    mock_response = MagicMock()
    mock_response.text = "Handwritten text content"
    mock_gemini_service.generate_content.return_value = mock_response
    
    mock_embed = MagicMock()
    mock_embed.values = [0.1, 0.2, 0.3]
    mock_gemini_service.embed_content.return_value = MagicMock(embeddings=[mock_embed])

    # Execute Pipeline
    await processor_service.process_file(file_id)

    # Verifications
    async with session_manager.session() as session:
        # 1. Verify Pages were created
        pages = (
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
        assert len(pages) > 0
        total_pages = len(pages)
        
        # 2. Verify OCR and Embedding content was saved
        for page in pages:
            assert page.content_hash is not None
            assert page.text_content == "Handwritten text content"
            assert page.embedding is not None

        # 3. Verify System Tasks are all COMPLETED
        tasks = (
            (
                await session.execute(
                    select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        )
        
        # Hashing (1) + Per-Page (3 types * N pages) + Summary (1)
        # Summary is implemented as False for run_if_needed, so it might not create a COMPLETED task 
        # unless it actually runs. My SummaryModule.run_if_needed returns False.
        # So: 1 (HASHING) + total_pages * 3 (PNG, OCR, EMBEDDING) 
        expected_task_count = 1 + (total_pages * 3)
        
        # Filter for COMPLETED
        completed_tasks = [t for t in tasks if t.status == "COMPLETED"]
        assert len(completed_tasks) == expected_task_count

        # 4. Verify PNGs exist in cache
        for i in range(total_pages):
            from supernote.server.utils.paths import get_page_png_path
            png_path = get_page_png_path(file_id, i)
            assert await blob_storage.exists(CACHE_BUCKET, png_path)

    print(f"Integration test passed with {total_pages} pages processed.")
