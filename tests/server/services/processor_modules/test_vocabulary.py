from pathlib import Path

import pytest

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.vocabulary import (
    VocabularyHarvestModule,
)
from supernote.server.services.vocabulary import VocabularyService
from supernote.server.utils.tasks import get_task

USER_ID = 100
FILE_ID = 999


@pytest.fixture
def vocabulary_service(session_manager: DatabaseSessionManager) -> VocabularyService:
    return VocabularyService(session_manager)


@pytest.fixture
def harvest_module(
    file_service: FileService, vocabulary_service: VocabularyService
) -> VocabularyHarvestModule:
    return VocabularyHarvestModule(
        file_service=file_service, vocabulary_service=vocabulary_service
    )


async def _store_note(
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    note_path: Path,
    storage_key: str | None = "note_storage_key",
) -> None:
    if storage_key:
        await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=FILE_ID,
                user_id=USER_ID,
                storage_key=storage_key,
                file_name="stroller.note",
                directory_id=0,
            )
        )
        await session.commit()


async def test_harvests_device_keywords(
    harvest_module: VocabularyHarvestModule,
    vocabulary_service: VocabularyService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_data_dir: Path,
) -> None:
    await _store_note(
        session_manager, blob_storage, test_data_dir / "mmujynya" / "stroller.note"
    )

    assert await harvest_module.run(FILE_ID, session_manager)

    terms = await vocabulary_service.terms_for_notebook(USER_ID, FILE_ID)
    assert terms == ["ks-tilt", "ks-trapezoid", "ks-shapes"]
    task = await get_task(
        session_manager, FILE_ID, TaskType.VOCABULARY_HARVEST, "global"
    )
    assert task is not None and task.status == ProcessingStatus.COMPLETED

    # Runs on every pass, since keywords change without changing page hashes
    assert await harvest_module.run_if_needed(FILE_ID, session_manager)


async def test_note_without_keywords(
    harvest_module: VocabularyHarvestModule,
    vocabulary_service: VocabularyService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    await _store_note(session_manager, blob_storage, test_note_path)
    assert await harvest_module.run(FILE_ID, session_manager)
    assert await vocabulary_service.list_terms(USER_ID) == []


async def test_file_without_content_is_skipped(
    harvest_module: VocabularyHarvestModule,
    vocabulary_service: VocabularyService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    await _store_note(session_manager, blob_storage, test_note_path, storage_key=None)
    assert await harvest_module.run(FILE_ID, session_manager)
    assert await harvest_module.run(12345, session_manager)
    assert await vocabulary_service.list_terms(USER_ID) == []
