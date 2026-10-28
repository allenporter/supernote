"""Unit tests for ConversionService."""

from pathlib import Path

import pytest

from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.exceptions import FileError, FileNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.services.conversion import ConversionService, ConvertedBlob
from supernote.server.services.file import FileService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_conversion_pdf_path


async def _read(blob_storage: BlobStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in blob_storage.get(CACHE_BUCKET, key)])


@pytest.fixture
def conversion_service(
    storage_root: Path,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    user_service: UserService,
) -> ConversionService:
    file_service = FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
    )
    summary_service = SummaryService(
        user_service=user_service, session_manager=session_manager
    )
    processor_service = ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )
    processor_service.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        png=PngConversionModule(file_service=file_service),
    )
    return ConversionService(
        session_manager=session_manager,
        blob_storage=blob_storage,
        user_service=user_service,
        processor_service=processor_service,
    )


async def test_convert_note_to_png_and_resolve_page(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5001
    storage_key = "note_5001.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, test_note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="My_Notebook.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_5001",
            )
        )
        await session.commit()

    page_numbers = await conversion_service.convert_note_to_png(user_email, file_id)
    assert len(page_numbers) > 0
    assert page_numbers[0] == 0

    blob = await conversion_service.get_note_png_page(user_email, file_id, 0)
    assert blob is not None
    assert blob.file_name == "My_Notebook_page_0.png"
    assert await blob_storage.exists(CACHE_BUCKET, blob.storage_key)

    # Non-existent page or unknown user returns None
    assert await conversion_service.get_note_png_page(user_email, file_id, 999) is None
    assert (
        await conversion_service.get_note_png_page("unknown@example.com", file_id, 0)
        is None
    )


async def test_convert_note_to_pdf_and_resolve(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5002
    storage_key = "note_5002.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, test_note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="Project_Plan.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_5002",
            )
        )
        await session.commit()

    assert await conversion_service.get_note_pdf(user_email, file_id) is None

    await conversion_service.convert_note_to_pdf(user_email, file_id, page_no_list=[])
    full_key = get_conversion_pdf_path(test_user_id, file_id, "md5_5002")
    full_pdf = await _read(blob_storage, full_key)

    # A page selection is stored apart from the full export it must not replace
    assert await conversion_service.get_note_pdf(user_email, file_id, [0]) is None
    await conversion_service.convert_note_to_pdf(user_email, file_id, page_no_list=[0])

    assert await conversion_service.get_note_pdf(user_email, file_id) == ConvertedBlob(
        storage_key=full_key,
        file_name="Project_Plan.pdf",
    )
    assert await _read(blob_storage, full_key) == full_pdf
    assert await conversion_service.get_note_pdf(
        user_email, file_id, [0]
    ) == ConvertedBlob(
        storage_key=get_conversion_pdf_path(test_user_id, file_id, "md5_5002", [0]),
        file_name="Project_Plan.pdf",
    )


async def test_conversion_service_validation_errors(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    user_email = "test@example.com"

    with pytest.raises(FileNotFound):
        await conversion_service.convert_note_to_png(user_email, 99999)

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=5003,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="MissingMd5.note",
                    is_folder="N",
                    storage_key="k5003",
                    md5=None,
                ),
                UserFileDO(
                    id=5004,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="MissingStorageKey.note",
                    is_folder="N",
                    storage_key=None,
                    md5="md5_5004",
                ),
            ]
        )
        await session.commit()

    with pytest.raises(FileError, match="missing MD5"):
        await conversion_service.convert_note_to_png(user_email, 5003)

    with pytest.raises(FileNotFound, match="no content"):
        await conversion_service.convert_note_to_png(user_email, 5004)
