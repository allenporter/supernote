import pytest
from sqlalchemy import select

from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ocr import OcrModule
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


async def test_ocr_skips_llm_call_for_blank_page(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    fake_ocr_model: FakeOcrModel,
) -> None:
    """Verify blank pages (has_drawables=False) write empty text_content and complete without calling OcrModel."""
    file_id = 1005
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="blank_key",
                file_name="blank.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p_blank",
                content_hash="h_blank",
                text_content=None,
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p_blank",
                content_hash="h_blank",
                has_ink=False,
                has_drawables=False,
            )
        )
        await session.commit()

    assert (
        await ocr_module.run(file_id, session_manager, page_index=0, page_id="p_blank")
        is True
    )
    assert fake_ocr_model.calls == []

    async with session_manager.session() as session:
        content = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        assert content.text_content == ""

        task = (
            await session.execute(
                select(SystemTaskDO)
                .where(SystemTaskDO.file_id == file_id)
                .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                .where(SystemTaskDO.key == "page_p_blank")
            )
        ).scalar_one()
        assert task.status == "COMPLETED"
