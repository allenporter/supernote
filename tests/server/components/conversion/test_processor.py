import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from supernote.server.components.conversion.processor import (
    PngConversionModule,
)
from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.utils.paths import get_page_png_path
from tests.server.components.conftest import LoadComponents


@pytest.fixture
def png_conversion_module(file_service: FileService) -> PngConversionModule:
    return PngConversionModule(file_service=file_service)


async def test_process_png_conversion_success(
    png_conversion_module: PngConversionModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """Integration test using a real .note file and real FileService."""

    # Setup Data
    user_id = 100
    file_id = 999
    storage_key = "test_note_storage_key_png"
    page_index = 0

    # Read real test file
    if not test_note_path.exists():
        pytest.skip(f"Test file not found at {test_note_path}")

    file_content = test_note_path.read_bytes()

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
        # Add NotePageContentDO so page_id exists
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=page_index,
                page_id="p0",
                content_hash="hash",
            )
        )
        await session.commit()

    # Run full module lifecycle
    await png_conversion_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0", user_id=user_id
    )

    # Assertions
    async with session_manager.session() as session:
        # Check Task Status
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.entity_id == file_id)
                    .where(SystemTaskDO.task_type == "PNG_CONVERSION")
                    .where(SystemTaskDO.key == "page_p0")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        if task.status != "COMPLETED":
            print(f"Task Failed with error: {task.last_error}")
        assert task.status == "COMPLETED"
        assert task.data == "v2"

    # Check Blob Output
    expected_blob_path = get_page_png_path(file_id, "p0")

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


@pytest.mark.parametrize(
    ("load_web_ui", "notebook_preview", "has_ocr", "expected_png_enabled"),
    [
        (True, True, False, True),
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, True),
    ],
)
async def test_async_setup_processor_registers_png_conversion_stage(
    component_core: ServerCore,
    load_components: LoadComponents,
    load_web_ui: bool,
    notebook_preview: bool,
    has_ocr: bool,
    expected_png_enabled: bool,
) -> None:
    """ConversionComponent registers PngConversionModule and toggles enabled by loaded web_ui/preview/OCR."""
    domains = ("conversion", "web_ui") if load_web_ui else ("conversion",)
    configs: dict[str, dict[str, object]] = {
        "conversion": {"notebook_preview": notebook_preview},
    }
    if has_ocr:
        component_core.config.gemini_api_key = "fake-key"
        component_core.config._sync_legacy_gemini_config()
        domains = (*domains, "gemini")

    await load_components(*domains, configs=configs, start=False)

    page_modules = component_core.app[PROCESSOR_SERVICE_KEY].page_modules
    png_mod = next(m for m in page_modules if isinstance(m, PngConversionModule))
    assert png_mod.enabled is expected_png_enabled
