from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteProcessingCompletedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.embedding import EmbeddingModule
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import (
    get_page_png_path,
    get_summary_group_id,
    get_summary_id,
    get_transcript_id,
)


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
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )


async def test_full_processing_pipeline_with_real_file(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_data_dir: Path,
    fake_ocr_model: FakeOcrModel,
    fake_embedding_model: FakeEmbeddingModel,
    fake_summary_model: FakeSummaryModel,
    authenticated_client: Client,
    user_service: UserService,
) -> None:
    """Full integration test using a real handwritten .note file."""

    # Setup Data
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)
    file_id = 999
    storage_key = "test_integration_note"
    written_note_path = test_data_dir / "dsummersl" / "sn2md_20260618.note"

    if not written_note_path.exists():
        pytest.skip(f"Test file not found at {written_note_path}")

    file_content = written_note_path.read_bytes()
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

    # Register modules with fake task models
    hashing = PageHashingModule(processor_service.file_service)
    png = PngConversionModule(processor_service.file_service)
    ocr = OcrModule(processor_service.file_service, fake_ocr_model)
    embedding = EmbeddingModule(processor_service.file_service, fake_embedding_model)
    summary = SummaryModule(
        file_service=processor_service.file_service,
        summary_service=processor_service.summary_service,
        summary_model=fake_summary_model,
    )

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    completed_events: list[NoteProcessingCompletedEvent] = []

    async def on_completed(event: object) -> None:
        if isinstance(event, NoteProcessingCompletedEvent):
            completed_events.append(event)

    processor_service.event_bus.subscribe(NoteProcessingCompletedEvent, on_completed)

    # Execute Pipeline
    await processor_service.process_file(file_id)

    # Verifications
    async with session_manager.session() as session:
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

        for page in pages:
            assert page.content_hash is not None
            assert page.text_content is not None
            assert page.text_content.startswith("Transcribed (")
            assert page.embedding is not None

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

        for page in pages:
            png_path = get_page_png_path(file_id, page.page_id)
            assert await blob_storage.exists(CACHE_BUCKET, png_path)

        summary_client = SummaryClient(authenticated_client)

        group_uuid = get_summary_group_id(storage_key)
        transcript_uuid = get_transcript_id(storage_key)
        summary_uuid = get_summary_id(storage_key)

        # Query groups
        group_response = await summary_client.query_groups()
        assert group_response.success
        group = next(
            (
                g
                for g in group_response.summary_do_list
                if g.unique_identifier == group_uuid
            ),
            None,
        )
        assert group is not None, (
            f"Group {group_uuid} not found in {group_response.summary_do_list}"
        )
        assert group.name == "real.note"

        # Query all summaries
        query_response = await summary_client.query_summaries()
        assert query_response.success
        summaries = query_response.summary_do_list
        assert len(summaries) >= 2  # At least transcript and AI summary

        # Find our specific summaries by unique identifier
        transcript = next(
            (s for s in summaries if s.unique_identifier == transcript_uuid), None
        )
        ai_summary = next(
            (s for s in summaries if s.unique_identifier == summary_uuid), None
        )

        assert transcript is not None, (
            f"Transcript {transcript_uuid} not found in {summaries}"
        )
        assert ai_summary is not None, (
            f"AI Summary {summary_uuid} not found in {summaries}"
        )

        # Check parent group linkage
        assert transcript.parent_unique_identifier == group_uuid
        assert ai_summary.parent_unique_identifier == group_uuid

        # Check transcript content
        assert transcript.content is not None
        assert "Transcribed (" in transcript.content
        assert transcript.data_source == "OCR"

        # Check AI summary content
        assert ai_summary.content is not None
        assert "Summary of (" in ai_summary.content
        assert ai_summary.data_source == "fake-summary-v1"

        # 6. Verify NoteProcessingCompletedEvent was published
        assert completed_events == [
            NoteProcessingCompletedEvent(
                file_id=file_id,
                user_id=user_id,
                file_path="real.note",
            )
        ]

    print(f"Integration test passed with {total_pages} pages processed.")


async def test_pipeline_skips_blank_pages_in_real_multi_page_note(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
    fake_embedding_model: FakeEmbeddingModel,
    fake_summary_model: FakeSummaryModel,
    authenticated_client: Client,
    user_service: UserService,
) -> None:
    """Verify blank template pages skip OCR and embedding LLM calls while still rendering PNGs and completing tasks."""
    note_path = (
        Path(__file__).parents[4]
        / "testdata"
        / "nelinory"
        / "A5X_TestNote_With_Pdf_Template.note"
    )
    user_id = await user_service.get_user_id("test@example.com")
    file_id = 1001
    storage_key = "pdf_template_mixed_blank"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name=note_path.name,
                directory_id=0,
            )
        )
        await session.commit()

    processor_service.register_modules(
        hashing=PageHashingModule(processor_service.file_service),
        png=PngConversionModule(processor_service.file_service),
        ocr=OcrModule(processor_service.file_service, fake_ocr_model),
        embedding=EmbeddingModule(processor_service.file_service, fake_embedding_model),
        summary=SummaryModule(
            file_service=processor_service.file_service,
            summary_service=processor_service.summary_service,
            summary_model=fake_summary_model,
        ),
    )

    await processor_service.process_file(file_id)

    # Pages 0 and 2 have ink; page 1 is an un-inked PDF template page.
    assert len(fake_ocr_model.calls) == 2
    assert len(fake_embedding_model.calls) == 2
    assert len(fake_summary_model.calls) == 1

    async with session_manager.session() as session:
        pages = list(
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
        assert len(pages) == 3
        assert pages[0].text_content and pages[0].embedding is not None
        assert pages[1].text_content == "" and pages[1].embedding is None
        assert pages[2].text_content and pages[2].embedding is not None

        for page in pages:
            assert await blob_storage.exists(
                CACHE_BUCKET, get_page_png_path(file_id, page.page_id)
            )

        completed_tasks = list(
            (
                await session.execute(
                    select(SystemTaskDO).where(
                        SystemTaskDO.file_id == file_id,
                        SystemTaskDO.status == "COMPLETED",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(completed_tasks) == 1 + (3 * 3) + 1

    # Missing-task recovery must NOT re-enqueue completed notes containing blank pages.
    await processor_service.recover_missing_tasks()
    assert file_id not in processor_service.processing_files
