import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
)
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import (
    get_summary_group_id,
    get_summary_id,
    get_transcript_id,
)
from supernote.server.utils.prompt_loader import PromptId


@pytest.fixture
def mock_summary_service() -> MagicMock:
    service = MagicMock(spec=SummaryService)
    service.upsert_group = AsyncMock()
    service.upsert_summary = AsyncMock()
    return service


@pytest.fixture
def summary_module(
    file_service: FileService,
    server_config_gemini: ServerConfig,
    mock_gemini_service: MagicMock,
    mock_summary_service: MagicMock,
) -> SummaryModule:
    return SummaryModule(
        file_service=file_service,
        config=server_config_gemini,
        gemini_service=mock_gemini_service,
        summary_service=mock_summary_service,
    )


async def test_summary_success(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
    mock_summary_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 100
    user_email = "test@example.com"
    file_id = 999
    storage_key = "test_storage_key"

    async with session_manager.session() as session:
        # User
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)

        # UserFile
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        # NotePageContent (2 pages)
        p1 = NotePageContentDO(
            file_id=file_id,
            page_index=0,
            page_id="p0",
            content_hash="h1",
            text_content="Page 1 text",
        )
        p2 = NotePageContentDO(
            file_id=file_id,
            page_index=1,
            page_id="p1",
            content_hash="h2",
            text_content="Page 2 text",
        )
        session.add(p1)
        session.add(p2)
        await session.commit()

    # Mock Gemini AI Response
    mock_response = MagicMock()
    # Return valid JSON matching the new segmented schema
    mock_response.text = json.dumps(
        {
            "segments": [
                {
                    "date_range": "2023-10-27",
                    "summary": "AI Summary Output",
                    "extracted_dates": ["2023-10-27"],
                    "page_refs": [1, 2],
                }
            ]
        }
    )
    mock_gemini_service.generate_content.return_value = mock_response

    # Mock PromptLoader
    with patch(
        "supernote.server.services.processor_modules.summary.PROMPT_LOADER"
    ) as mock_loader:
        # Provide a template that includes the placeholder
        mock_loader.get_prompt.return_value = "Generate {{TRANSCRIPT}}"

        # Run full module lifecycle
        await summary_module.run(file_id, session_manager)

        # Verifications
        # Verify PromptLoader called with correct filename
        mock_loader.get_prompt.assert_called_with(
            PromptId.SUMMARY_GENERATION, custom_type="real"
        )

        # Verify Gemini called with populated prompt
        call_args = mock_gemini_service.generate_content.call_args
        assert call_args is not None
        _, kwargs = call_args
        assert "Page 1 text" in kwargs["contents"]
        assert "Page 2 text" in kwargs["contents"]
        assert "Generate" in kwargs["contents"]

    # 1. Group Upsert
    group_call = mock_summary_service.upsert_group.call_args_list[0]
    assert group_call.args[0] == user_email
    dto_group = group_call.args[1]
    assert isinstance(dto_group, AddSummaryGroupDTO)
    assert dto_group.unique_identifier == get_summary_group_id(storage_key)
    assert dto_group.name == "real.note"

    # 2. Transcript Upsert
    transcript_call = mock_summary_service.upsert_summary.call_args_list[0]
    assert transcript_call.args[0] == user_email
    dto = transcript_call.args[1]
    assert isinstance(dto, AddSummaryDTO)
    assert dto.unique_identifier == get_transcript_id(storage_key)
    assert dto.parent_unique_identifier == get_summary_group_id(storage_key)
    assert dto.content is not None
    assert "Page 1 text" in dto.content
    assert "Page 2 text" in dto.content
    assert dto.data_source == "OCR"

    # 3. AI Summary Upsert
    ai_call = mock_summary_service.upsert_summary.call_args_list[1]
    assert ai_call.args[0] == user_email
    dto_ai = ai_call.args[1]
    assert dto_ai.unique_identifier == get_summary_id(storage_key)
    assert dto_ai.parent_unique_identifier == get_summary_group_id(storage_key)
    assert "## 2023-10-27" in dto_ai.content
    assert "AI Summary Output" in dto_ai.content
    assert dto_ai.data_source == "GEMINI"

    # Check Metadata
    assert dto_ai.metadata is not None
    meta = json.loads(dto_ai.metadata)
    assert meta[METADATA_SEGMENTS][0]["page_refs"] == [1, 2]

    # 4. Check Task Status
    async with session_manager.session() as session:
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert task is not None
        assert task.status == "COMPLETED"


async def test_summary_idempotency_update(
    file_service: FileService,
    server_config_gemini: ServerConfig,
    mock_gemini_service: MagicMock,
    session_manager: DatabaseSessionManager,
    user_service: UserService,
) -> None:
    """Rerunning the module against pre-existing rows updates them in place.

    Uses a real (non-mocked) SummaryService so the create-or-update-by-
    unique_identifier behavior that now lives in SummaryService.upsert_group /
    upsert_summary is exercised end-to-end via the module's delegation to it.
    """
    summary_service = SummaryService(user_service, session_manager)
    summary_module = SummaryModule(
        file_service=file_service,
        config=server_config_gemini,
        gemini_service=mock_gemini_service,
        summary_service=summary_service,
    )

    # Setup Data
    user_id = 101
    user_email = "update@example.com"
    file_id = 888
    storage_key = "update_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="update.note",
            directory_id=0,
        )
        session.add(user_file)
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h1",
                text_content="Some text",
            )
        )
        await session.commit()

    # Pre-create a group and an AI summary row with the same unique identifiers
    # the module will generate, so the run should update them in place.
    existing_group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=get_summary_group_id(storage_key),
            name="stale-name.note",
            md5_hash="stale-hash",
        ),
    )
    existing_ai_summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            unique_identifier=get_summary_id(storage_key),
            parent_unique_identifier=get_summary_group_id(storage_key),
            content="stale content",
            data_source="GEMINI",
        ),
    )

    # Mock Gemini
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "segments": [
                {
                    "date_range": "2023-10-28",
                    "summary": "New AI Summary",
                    "extracted_dates": [],
                    "page_refs": [3, 4],
                }
            ]
        }
    )
    mock_gemini_service.generate_content.return_value = mock_response

    # Run module
    await summary_module.run(file_id, session_manager)

    # Group should be updated in place, not duplicated.
    async with session_manager.session() as session:
        group_rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == get_summary_group_id(storage_key)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(group_rows) == 1
        assert group_rows[0].id == existing_group.id
        assert group_rows[0].name == "update.note"

    # Transcript should have been created fresh (didn't exist before).
    async with session_manager.session() as session:
        transcript_rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == get_transcript_id(storage_key)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(transcript_rows) == 1
        assert transcript_rows[0].parent_unique_identifier == get_summary_group_id(
            storage_key
        )

    # AI summary should be updated in place, not duplicated.
    async with session_manager.session() as session:
        summary_rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == get_summary_id(storage_key)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(summary_rows) == 1
        assert summary_rows[0].id == existing_ai_summary.id
        summary_content = summary_rows[0].content
        assert summary_content is not None
        assert "## 2023-10-28 (Pages 3, 4)" in summary_content
        assert "New AI Summary" in summary_content

        # Check Metadata JSON
        assert summary_rows[0].extra_metadata is not None
        meta = json.loads(summary_rows[0].extra_metadata)
        assert meta[METADATA_SEGMENTS][0]["page_refs"] == [3, 4]


async def test_summary_transcript_with_dates(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
    mock_summary_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 100
    user_email = "test@example.com"
    file_id = 123
    storage_key = "date_test_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="dates.note",
            directory_id=0,
        )
        session.add(user_file)

        # Page with date-encoded ID
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Content on Oct 27",
            )
        )
        await session.commit()

    # Mock Gemini (minimal)
    mock_response = MagicMock()
    mock_response.text = json.dumps({"segments": []})
    mock_gemini_service.generate_content.return_value = mock_response

    # Run full module lifecycle
    await summary_module.run(file_id, session_manager)

    # Verify Group was upserted
    mock_summary_service.upsert_group.assert_called_once()
    group_dto = mock_summary_service.upsert_group.call_args.args[1]
    assert group_dto.unique_identifier == get_summary_group_id(storage_key)
    assert group_dto.name == "dates.note"

    # Verify Transcript contains date and metadata and parent_unique_identifier
    transcript_call = mock_summary_service.upsert_summary.call_args_list[0]
    dto = transcript_call.args[1]
    assert dto.parent_unique_identifier == get_summary_group_id(storage_key)
    assert "--- Page 1 ---" in dto.content
    assert "Page ID: P20231027120000abc" in dto.content
    assert "Page Date (Inferred): 2023-10-27" in dto.content
