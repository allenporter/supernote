import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def png_conversion_module(file_service: FileService) -> PngConversionModule:
    return PngConversionModule(file_service=file_service)


@pytest.mark.asyncio
async def test_process_png_conversion_success(
    png_conversion_module: PngConversionModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Integration test using a real .note file and real FileService."""

    # 1. Setup Data
    user_id = 100
    file_id = 999
    storage_key = "test_note_storage_key_png"
    page_index = 0

    # Read real test file
    test_file_path = Path("tests/testdata/20251207_221454.note")
    if not test_file_path.exists():
        pytest.skip(f"Test file not found at {test_file_path}")

    file_content = test_file_path.read_bytes()

    # Write to Blob Storage
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

    # 2. Run Process
    await png_conversion_module.process(file_id, session_manager, page_index=page_index)

    # 3. Assertions
    async with session_manager.session() as session:
        # Check Task Status
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "PNG_CONVERSION")
                    .where(SystemTaskDO.key == f"page_{page_index}")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        if task.status != "COMPLETED":
            print(f"Task Failed with error: {task.last_error}")
        assert task.status == "COMPLETED"

    # Check Blob Output
    # Expected path no longer has caches/ prefix if helper changed, but helper returns full key.
    expected_blob_path = get_page_png_path(file_id, page_index)

    assert await blob_storage.exists(CACHE_BUCKET, expected_blob_path)

    # Verify Content is valid PNG
    content = b""
    async for chunk in blob_storage.get(CACHE_BUCKET, expected_blob_path):
        content += chunk
    assert content is not None

    with io.BytesIO(content) as buf:
        img = Image.open(buf)
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0
        print(f"Generated PNG size: {img.size}")
