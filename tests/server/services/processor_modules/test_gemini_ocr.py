from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.gemini_ocr import GeminiOcrModule
from supernote.server.utils.paths import get_page_png_path
from supernote.server.utils.prompt_loader import PromptId


@pytest.fixture
def gemini_ocr_module(
    file_service: FileService,
    server_config_gemini: ServerConfig,
    mock_gemini_service: MagicMock,
) -> GeminiOcrModule:
    return GeminiOcrModule(
        file_service=file_service,
        config=server_config_gemini,
        gemini_service=mock_gemini_service,
    )


async def test_process_ocr_success(
    gemini_ocr_module: GeminiOcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_gemini_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

    # Create dummy PNG
    png_content = b"fake-png-data"
    # Create dummy PNG
    png_content = b"fake-png-data"
    png_path = get_page_png_path(file_id, "p0")
    await blob_storage.put(CACHE_BUCKET, png_path, png_content)

    async with session_manager.session() as session:
        # UserFile
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        # NotePageContent (Pre-existing from hashing)
        content = NotePageContentDO(
            file_id=file_id,
            page_index=page_index,
            page_id="p0",
            content_hash="somehash",
        )
        session.add(content)
        await session.commit()

    # Mock Gemini API Response
    mock_response = MagicMock()
    mock_response.text = "Handwritten text content"
    mock_gemini_service.generate_content.return_value = mock_response

    # Mock PromptLoader
    with patch("supernote.server.utils.gemini_content.PROMPT_LOADER") as mock_loader:
        mock_loader.get_prompt.return_value = "Transcribe this page."

        # Run full module lifecycle
        await gemini_ocr_module.run(
            file_id, session_manager, page_index=page_index, page_id="p0"
        )

        # Verifications
        # Verify PromptLoader called with correct filename
        mock_loader.get_prompt.assert_called_with(
            PromptId.OCR_TRANSCRIPTION, custom_type="real"
        )

    # Verify API Call
    call_args = mock_gemini_service.generate_content.call_args
    assert call_args is not None
    _, kwargs = call_args
    assert kwargs["model"] == "gemini-2.0-flash-exp"

    content_obj = kwargs["contents"][0]
    parts = content_obj.parts
    assert len(parts) == 2
    assert "Transcribe this page." in parts[0].text
    assert "Notebook Filename: real.note" in parts[0].text
    assert parts[1].inline_data.data == png_content
    # Verify config passed
    assert kwargs["config"] == {"media_resolution": "media_resolution_high"}

    # Verify DB Updates
    async with session_manager.session() as session:
        # Check Content Update
        updated_content = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == page_index)
                )
            )
            .scalars()
            .first()
        )

        assert updated_content is not None
        assert updated_content.text_content == "Handwritten text content"

        # Check Task Status
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                    .where(SystemTaskDO.key == "page_p0")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"


async def test_ocr_run_if_needed_disabled(
    gemini_ocr_module: GeminiOcrModule,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
) -> None:
    # Disable Gemini
    mock_gemini_service.is_configured = False

    # Should return False
    assert (
        await gemini_ocr_module.run_if_needed(
            1, session_manager, page_index=0, page_id="p0"
        )
        is False
    )

    # run() should still return True (skipped success)
    assert (
        await gemini_ocr_module.run(1, session_manager, page_index=0, page_id="p0")
        is True
    )


async def test_ocr_with_inferred_date(
    gemini_ocr_module: GeminiOcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_gemini_service: MagicMock,
) -> None:
    # Setup Data
    file_id = 123
    page_id = "P20231027123456"

    # Create dummy PNG
    png_path = get_page_png_path(file_id, page_id)
    await blob_storage.put(CACHE_BUCKET, png_path, b"data")

    async with session_manager.session() as session:
        session.add(
            UserFileDO(id=file_id, user_id=1, file_name="test.note", directory_id=0)
        )
        session.add(NotePageContentDO(file_id=file_id, page_index=0, page_id=page_id))
        await session.commit()

    # Mock Gemini
    mock_response = MagicMock()
    mock_response.text = "OCR text"
    mock_gemini_service.generate_content.return_value = mock_response

    # Mock PromptLoader
    with patch("supernote.server.utils.gemini_content.PROMPT_LOADER") as mock_loader:
        mock_loader.get_prompt.return_value = "Prompt"
        await gemini_ocr_module.run(
            file_id, session_manager, page_index=0, page_id=page_id
        )

    # Verify Prompt
    call_args = mock_gemini_service.generate_content.call_args
    _, kwargs = call_args
    prompt_text = kwargs["contents"][0].parts[0].text
    assert "--- Page 1 ---" in prompt_text
    assert "Notebook Filename: test.note" in prompt_text
    assert "Page ID: P20231027123456" in prompt_text
    assert "Page Date (Inferred): 2023-10-27" in prompt_text
