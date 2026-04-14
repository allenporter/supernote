from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.utils.paths import get_page_png_path
from supernote.server.utils.prompt_loader import PromptId


@pytest.fixture
def gemini_ocr_module(
    file_service: FileService,
    mock_gemini_service: MagicMock,
) -> OcrModule:
    return OcrModule(
        file_service=file_service,
        ai_service=mock_gemini_service,
    )


async def test_process_ocr_success(
    gemini_ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_gemini_service: MagicMock,
) -> None:
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

    png_content = b"fake-png-data"
    png_path = get_page_png_path(file_id, "p0")
    await blob_storage.put(CACHE_BUCKET, png_path, png_content)

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        content = NotePageContentDO(
            file_id=file_id,
            page_index=page_index,
            page_id="p0",
            content_hash="somehash",
        )
        session.add(content)
        await session.commit()

    mock_gemini_service.ocr_image.return_value = "Handwritten text content"

    with patch(
        "supernote.server.services.processor_modules.ocr.PROMPT_LOADER"
    ) as mock_loader:
        mock_loader.get_prompt.return_value = "Transcribe this page."
        await gemini_ocr_module.run(
            file_id, session_manager, page_index=page_index, page_id="p0"
        )
        mock_loader.get_prompt.assert_called_with(
            PromptId.OCR_TRANSCRIPTION, custom_type="real"
        )

    # Verify ocr_image called with correct png_data and prompt containing metadata
    call_args = mock_gemini_service.ocr_image.call_args
    assert call_args is not None
    called_png, called_prompt = call_args.args
    assert called_png == png_content
    assert "Transcribe this page." in called_prompt
    assert "Notebook Filename: real.note" in called_prompt

    # Verify DB Updates
    async with session_manager.session() as session:
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
    gemini_ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
) -> None:
    mock_gemini_service.is_configured = False

    assert (
        await gemini_ocr_module.run_if_needed(1, session_manager, page_index=0, page_id="p0")
        is False
    )
    assert await gemini_ocr_module.run(1, session_manager, page_index=0, page_id="p0") is True


async def test_ocr_with_inferred_date(
    gemini_ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_gemini_service: MagicMock,
) -> None:
    file_id = 123
    page_id = "P20231027123456"

    png_path = get_page_png_path(file_id, page_id)
    await blob_storage.put(CACHE_BUCKET, png_path, b"data")

    async with session_manager.session() as session:
        session.add(
            UserFileDO(id=file_id, user_id=1, file_name="test.note", directory_id=0)
        )
        session.add(NotePageContentDO(file_id=file_id, page_index=0, page_id=page_id))
        await session.commit()

    mock_gemini_service.ocr_image.return_value = "OCR text"

    with patch(
        "supernote.server.services.processor_modules.ocr.PROMPT_LOADER"
    ) as mock_loader:
        mock_loader.get_prompt.return_value = "Prompt"
        await gemini_ocr_module.run(file_id, session_manager, page_index=0, page_id=page_id)

    _, called_prompt = mock_gemini_service.ocr_image.call_args.args
    assert "--- Page 1 ---" in called_prompt
    assert "Notebook Filename: test.note" in called_prompt
    assert "Page ID: P20231027123456" in called_prompt
    assert "Page Date (Inferred): 2023-10-27" in called_prompt
