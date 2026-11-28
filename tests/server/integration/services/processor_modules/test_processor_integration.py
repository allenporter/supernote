from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import select

from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.server.components.ai import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
)
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.fake_ai.ocr import FakeOcrModel
from supernote.server.components.fake_ai.summary import FakeSummaryModel
from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NoteProcessingCompletedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService
from supernote.server.utils.paths import (
    AI_SUMMARIES_GROUP_NAME,
    get_ai_summaries_group_id,
    get_page_png_path,
    get_summary_id,
)


@pytest.fixture
def server_config(server_config: ServerConfig) -> ServerConfig:
    """Configure fake_ai models so create_app wires the full processor pipeline."""
    server_config.ai = AiConfig(
        providers={"fake_ai": ProviderConfig()},
        ocr=ModelConfig(provider="fake_ai", model="fake-ocr-v1"),
        embedding=ModelConfig(provider="fake_ai", model="fake-embedding-v1"),
        summary=ModelConfig(provider="fake_ai", model="fake-summary-v1"),
    )
    return server_config


async def test_full_processing_pipeline_with_real_file(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_data_dir: Path,
    authenticated_client: Client,
    user_service: UserService,
) -> None:
    """Full integration test using a real handwritten .note file."""
    assert client.app is not None
    processor_service = client.app[PROCESSOR_SERVICE_KEY]

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

    completed_events: list[NoteProcessingCompletedEvent] = []

    async def on_completed(event: object) -> None:
        if isinstance(event, NoteProcessingCompletedEvent):
            completed_events.append(event)

    processor_service.event_bus.subscribe(NoteProcessingCompletedEvent, on_completed)

    # Execute Pipeline
    await processor_service.process_file(file_id, user_id=user_id)

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
                    select(SystemTaskDO).where(SystemTaskDO.entity_id == file_id)
                )
            )
            .scalars()
            .all()
        )

        # Hashing (1) + Metadata (1) + Per-Page (3 types * N pages) + Summary (1)
        expected_task_count = 2 + (total_pages * 3) + 1

        # Filter for COMPLETED
        completed_tasks = [t for t in tasks if t.status == "COMPLETED"]
        assert len(completed_tasks) == expected_task_count

        for page in pages:
            png_path = get_page_png_path(file_id, page.page_id)
            assert await blob_storage.exists(CACHE_BUCKET, png_path)

        summary_client = SummaryClient(authenticated_client)

        group_uuid = get_ai_summaries_group_id(user_id)
        summary_uuid = get_summary_id(user_id, file_id)

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
        assert group.name == AI_SUMMARIES_GROUP_NAME

        # Query all summaries
        query_response = await summary_client.query_summaries()
        assert query_response.success
        summaries = query_response.summary_do_list
        assert all((s.data_source or "").upper() != "OCR" for s in summaries)

        ai_summary = next(
            (s for s in summaries if s.unique_identifier == summary_uuid), None
        )
        assert ai_summary is not None, (
            f"AI Summary {summary_uuid} not found in {summaries}"
        )
        assert ai_summary.parent_unique_identifier == group_uuid
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
    client: TestClient,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_data_dir: Path,
) -> None:
    """Verify blank template pages skip OCR and embedding LLM calls while still rendering PNGs and completing tasks."""
    assert client.app is not None
    processor_service = client.app[PROCESSOR_SERVICE_KEY]

    def _unwrap(model: object) -> object:
        while hasattr(model, "_model"):
            model = model._model
        return model

    fake_ocr_model = _unwrap(client.app[OCR_MODEL_KEY])
    fake_embedding_model = _unwrap(client.app[EMBEDDING_MODEL_KEY])
    fake_summary_model = _unwrap(client.app[SUMMARY_MODEL_KEY])
    assert isinstance(fake_ocr_model, FakeOcrModel)
    assert isinstance(fake_embedding_model, FakeEmbeddingModel)
    assert isinstance(fake_summary_model, FakeSummaryModel)

    note_path = test_data_dir / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    user_id = 77
    file_id = 1001
    storage_key = "pdf_template_mixed_blank"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="mixed@example.com", password_md5="hash"))
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

    await processor_service.process_file(file_id, user_id=user_id)

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
                        SystemTaskDO.entity_id == file_id,
                        SystemTaskDO.status == "COMPLETED",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(completed_tasks) == 2 + (3 * 3) + 1
