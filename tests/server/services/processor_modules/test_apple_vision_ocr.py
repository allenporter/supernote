from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.apple_vision_ocr import (
    AppleVisionOcrModule,
)
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def apple_vision_ocr_module(
    file_service: FileService,
    server_config_apple_vision_ocr: ServerConfig,
    mock_apple_vision_ocr_service: MagicMock,
) -> AppleVisionOcrModule:
    return AppleVisionOcrModule(
        file_service=file_service,
        config=server_config_apple_vision_ocr,
        apple_vision_ocr_service=mock_apple_vision_ocr_service,
    )


async def test_process_ocr_success(
    apple_vision_ocr_module: AppleVisionOcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_apple_vision_ocr_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

    # Create dummy PNG
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

    # Mock Apple Vision OCR API Response
    mock_apple_vision_ocr_service.extract_text.return_value = "Handwritten text content"

    # Run full module lifecycle
    await apple_vision_ocr_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0"
    )

    # Verify API Call
    mock_apple_vision_ocr_service.extract_text.assert_called_once_with(png_content)

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


async def test_ocr_run_if_needed_png_missing(
    apple_vision_ocr_module: AppleVisionOcrModule,
    session_manager: DatabaseSessionManager,
) -> None:
    # No PNG has been put in blob storage for this file/page.
    assert (
        await apple_vision_ocr_module.run_if_needed(
            1, session_manager, page_index=0, page_id="p0"
        )
        is False
    )


async def test_ocr_run_if_needed_disabled(
    apple_vision_ocr_module: AppleVisionOcrModule,
    session_manager: DatabaseSessionManager,
    mock_apple_vision_ocr_service: MagicMock,
) -> None:
    # Disable Apple Vision OCR
    mock_apple_vision_ocr_service.is_configured = False

    # Should return False
    assert (
        await apple_vision_ocr_module.run_if_needed(
            1, session_manager, page_index=0, page_id="p0"
        )
        is False
    )

    # run() should still return True (skipped success)
    assert (
        await apple_vision_ocr_module.run(
            1, session_manager, page_index=0, page_id="p0"
        )
        is True
    )


async def test_process_ocr_service_failure(
    apple_vision_ocr_module: AppleVisionOcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    mock_apple_vision_ocr_service: MagicMock,
) -> None:
    file_id = 1001
    page_index = 0

    png_path = get_page_png_path(file_id, "p0")
    await blob_storage.put(CACHE_BUCKET, png_path, b"fake-png-data")

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=100,
            storage_key="key",
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

    mock_apple_vision_ocr_service.extract_text.side_effect = ValueError(
        "Apple Vision OCR request failed"
    )

    # run() catches the exception and marks the task FAILED rather than raising.
    result = await apple_vision_ocr_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0"
    )
    assert result is False

    async with session_manager.session() as session:
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
        assert task.status == "FAILED"
