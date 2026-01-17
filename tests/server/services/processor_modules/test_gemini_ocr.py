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
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules.gemini_ocr import GeminiOcrModule
from supernote.server.utils.paths import get_page_png_path




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


@pytest.mark.asyncio
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
    png_path = get_page_png_path(file_id, page_index)
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
            file_id=file_id, page_index=page_index, content_hash="somehash"
        )
        session.add(content)
        await session.commit()

    # Mock Gemini API Response
    mock_response = MagicMock()
    mock_response.text = "Handwritten text content"
    mock_gemini_service.generate_content.return_value = mock_response

    # Run full module lifecycle
    await gemini_ocr_module.run(file_id, session_manager, page_index=page_index)

    # Verifications
    # Verify API Call
    call_args = mock_gemini_service.generate_content.call_args
    assert call_args is not None
    _, kwargs = call_args
    assert kwargs["model"] == "gemini-2.0-flash-exp"

    content_obj = kwargs["contents"][0]
    parts = content_obj.parts
    assert len(parts) == 2
    assert parts[0].text.startswith("Transcribe")
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
                    .where(SystemTaskDO.key == f"page_{page_index}")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"
