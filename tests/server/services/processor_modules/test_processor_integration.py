from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
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
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_summary_id, get_transcript_id


@pytest.fixture
def summary_service(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> SummaryService:
    return SummaryService(user_service=user_service, session_manager=session_manager)


@pytest.fixture
def processor_service(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    summary_service: SummaryService,
) -> ProcessorService:
    return ProcessorService(
        event_bus=MagicMock(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )


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
        # User
        user = UserDO(id=user_id, email="test@example.com", password_md5="hash")
        session.add(user)

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
    summary = SummaryModule(
        file_service=processor_service.file_service,
        config=server_config_gemini,
        gemini_service=mock_gemini_service,
        summary_service=processor_service.summary_service,
    )

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
        expected_task_count = 1 + (total_pages * 3) + 1

        # Filter for COMPLETED
        completed_tasks = [t for t in tasks if t.status == "COMPLETED"]
        assert len(completed_tasks) == expected_task_count

        # 4. Verify PNGs exist in cache
        # 4. Verify PNGs exist in cache
        for page in pages:
            from supernote.server.utils.paths import get_page_png_path

            png_path = get_page_png_path(file_id, page.page_id)
            assert await blob_storage.exists(CACHE_BUCKET, png_path)

        # 5. Verify Summary existence in DB
        summaries = (
            (
                await session.execute(
                    select(SummaryDO)
                    .where(SummaryDO.file_id == file_id)
                    .order_by(SummaryDO.unique_identifier)
                )
            )
            .scalars()
            .all()
        )
        assert len(summaries) == 2

        # Check transcript
        transcript = summaries[1]  # -transcript comes after -summary
        assert transcript.unique_identifier == get_transcript_id(storage_key)
        assert transcript.content is not None
        assert "Handwritten text content" in transcript.content
        assert transcript.data_source == "OCR"

        # Check AI summary
        ai_summary = summaries[0]
        assert ai_summary.unique_identifier == get_summary_id(storage_key)
        assert ai_summary.content == "Handwritten text content"  # Mocked response
        assert ai_summary.data_source == "GEMINI"

    print(f"Integration test passed with {total_pages} pages processed.")
