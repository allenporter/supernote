import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    SummaryItem,
)
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.paths import get_summary_id, get_transcript_id
from supernote.server.utils.prompt_loader import PromptId


@pytest.fixture
def mock_summary_service() -> MagicMock:
    service = MagicMock(spec=SummaryService)
    service.get_summary_by_uuid = AsyncMock(return_value=None)
    service.add_summary = AsyncMock()
    service.update_summary = AsyncMock()
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

    # 1. Transcript Upsert
    transcript_call = mock_summary_service.add_summary.call_args_list[0]
    assert transcript_call.args[0] == user_email
    dto = transcript_call.args[1]
    assert isinstance(dto, AddSummaryDTO)
    assert dto.unique_identifier == get_transcript_id(storage_key)
    assert dto.content is not None
    assert "Page 1 text" in dto.content
    assert "Page 2 text" in dto.content
    assert dto.data_source == "OCR"

    # 2. AI Summary Upsert
    ai_call = mock_summary_service.add_summary.call_args_list[1]
    assert ai_call.args[0] == user_email
    dto_ai = ai_call.args[1]
    assert dto_ai.unique_identifier == get_summary_id(storage_key)
    assert "## 2023-10-27" in dto_ai.content
    assert "AI Summary Output" in dto_ai.content
    assert dto_ai.data_source == "GEMINI"

    # Check Metadata
    assert dto_ai.metadata is not None
    meta = json.loads(dto_ai.metadata)
    assert meta[METADATA_SEGMENTS][0]["page_refs"] == [1, 2]

    # 3. Check Task Status
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
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
    mock_summary_service: MagicMock,
) -> None:
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

    # Mock Existing Summary
    existing_summary = SummaryItem(id=11, unique_identifier=get_summary_id(storage_key))
    # 1st call (transcript): return None -> calls add_summary
    # 2nd call (ai summary): return existing -> calls update_summary
    mock_summary_service.get_summary_by_uuid.side_effect = [None, existing_summary]

    # Run module
    await summary_module.run(file_id, session_manager)

    # Transcript should be added
    mock_summary_service.add_summary.assert_called_once()
    transcript_dto = mock_summary_service.add_summary.call_args.args[1]
    assert transcript_dto.unique_identifier == get_transcript_id(storage_key)

    # AI Summary should be updated
    mock_summary_service.update_summary.assert_called_once()
    update_call = mock_summary_service.update_summary.call_args
    assert update_call is not None

    # helper to get DTO from call args (user_email, dto)
    update_dto = update_call.args[1]

    assert update_dto.id == existing_summary.id
    assert "## 2023-10-28 (Pages 3, 4)" in update_dto.content
    assert "New AI Summary" in update_dto.content

    # Check Metadata JSON
    assert update_dto.metadata is not None
    meta = json.loads(update_dto.metadata)
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

    # Verify Transcript contains date and metadata
    transcript_call = mock_summary_service.add_summary.call_args_list[0]
    dto = transcript_call.args[1]
    assert "--- Page 1 ---" in dto.content
    assert "Page ID: P20231027120000abc" in dto.content
    assert "Page Date (Inferred): 2023-10-27" in dto.content
