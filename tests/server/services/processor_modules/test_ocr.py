import pytest
from sqlalchemy import select

from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.services.vocabulary import VocabularyService
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def ocr_module(
    file_service: FileService,
    fake_ocr_model: FakeOcrModel,
) -> OcrModule:
    return OcrModule(
        file_service=file_service,
        ocr_model=fake_ocr_model,
    )


async def test_process_ocr_success(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
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

    await ocr_module.run(file_id, session_manager, page_index=page_index, page_id="p0")

    assert len(fake_ocr_model.calls) == 1
    called_png, called_prompt = fake_ocr_model.calls[0]
    assert called_png == png_content
    assert "--- Page 1 ---" in called_prompt
    assert "Notebook Filename: real.note" in called_prompt
    assert "Page ID: p0" in called_prompt

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
        assert updated_content.text_content == f"Transcribed ({len(png_content)} bytes)"

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
    file_service: FileService,
    session_manager: DatabaseSessionManager,
) -> None:
    module = OcrModule(file_service=file_service, ocr_model=None)

    assert (
        await module.run_if_needed(1, session_manager, page_index=0, page_id="p0")
        is False
    )

    # run() should still return True (skipped success)
    assert await module.run(1, session_manager, page_index=0, page_id="p0") is True


async def test_process_ocr_includes_vocabulary(
    file_service: FileService,
    fake_ocr_model: FakeOcrModel,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    vocabulary_service = VocabularyService(session_manager)
    ocr_module = OcrModule(
        file_service=file_service,
        ocr_model=fake_ocr_model,
        vocabulary_service=vocabulary_service,
    )
    user_id = 100
    file_id = 1001
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"png")
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="k",
                file_name="real.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id, page_index=0, page_id="p0", content_hash="h"
            )
        )
        await session.commit()
    await vocabulary_service.add_terms(user_id, ["Lovelace"])

    await ocr_module.run(file_id, session_manager, page_index=0, page_id="p0")

    [(_, prompt)] = fake_ocr_model.calls
    assert "These names and terms may appear in the text: Lovelace." in prompt
