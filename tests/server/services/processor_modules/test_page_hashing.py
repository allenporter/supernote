from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule


@pytest.fixture
def page_hashing_module(file_service: FileService) -> PageHashingModule:
    return PageHashingModule(file_service=file_service)


async def test_process_with_real_file(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """Integration test using a real .note file and real FileService."""

    # Setup Data
    user_id = 100
    file_id = 999
    storage_key = "test_note_storage_key"

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
        await session.commit()

    # Run module lifecycle (Real Parser, Real File)
    await page_hashing_module.run(file_id, session_manager)

    # Assertions
    async with session_manager.session() as session:
        # Check Pages
        pages = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )

        # We don't know exactly how many pages, but it should be > 0
        print(f"Found {len(pages)} pages")
        assert len(pages) > 0

        first_page = pages[0]
        assert first_page is not None
        assert first_page.content_hash is not None
        assert len(first_page.content_hash) > 0

        # Capture the hash to verify change detection later
        original_hash = first_page.content_hash

        # Check Task
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "HASHING")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"

    # Test Change Detection (Simulated)
    # Since we can't easily edit the binary .note file to change content,
    # we will Simulate a change by manually modifying the DB hash to be wrong.
    # Then running process again should revert it to the correct hash.

    async with session_manager.session() as session:
        page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == 0)
                )
            )
            .scalars()
            .first()
        )

        assert page is not None
        page.content_hash = "FAKE_HASH"
        # Set some dummy content that should be cleared
        page.text_content = "dummy_ocr"
        page.embedding = "[0.1, 0.2]"
        page.embedding_model = "old-model"

        # Add mock downstream tasks that should be invalidated (deleted)
        ocr_task = SystemTaskDO(
            file_id=file_id,
            task_type="OCR_EXTRACTION",
            key=f"page_{page.page_id}",
            status="COMPLETED",
        )
        summary_task = SystemTaskDO(
            file_id=file_id,
            task_type="SUMMARY_GENERATION",
            key="global",
            status="COMPLETED",
        )
        downstream_global_task = SystemTaskDO(
            file_id=file_id,
            task_type="DOWNSTREAM_GLOBAL_TASK",
            key="global",
            status="COMPLETED",
        )
        session.add_all([ocr_task, summary_task, downstream_global_task])
        await session.commit()

    # Run process again
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == 0)
                )
            )
            .scalars()
            .first()
        )

        assert page is not None
        # Hash should be back to original (real) hash
        assert page.content_hash == original_hash
        # Text content, embedding, and embedding_model should be cleared because we simulated a "change" (Fake -> Real)
        assert page.text_content is None
        assert page.embedding is None
        assert page.embedding_model is None

        # Check that the downstream page and summary tasks were invalidated (deleted)
        invalidated_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                    .where(SystemTaskDO.key == f"page_{page.page_id}")
                )
            )
            .scalars()
            .first()
        )
        assert invalidated_task is None

        invalidated_summary_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert invalidated_summary_task is None

        invalidated_downstream_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "DOWNSTREAM_GLOBAL_TASK")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert invalidated_downstream_task is None

    # Test Deletion
    # We will simulate deletion by manually adding an extra page that doesn't exist in the file.
    # The process should remove it.

    extra_page_index = len(pages) + 5  # Safely out of bounds
    async with session_manager.session() as session:
        extra_page = NotePageContentDO(
            file_id=file_id,
            page_index=extra_page_index,
            page_id="trash_id",
            content_hash="trash",
        )
        session.add(extra_page)
        await session.commit()

    # Run process again
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        # Verify extra page is gone
        missing_page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == extra_page_index)
                )
            )
            .scalars()
            .first()
        )

        assert missing_page is None

        # Verify original pages still there
        current_pages = (
            (
                await session.execute(
                    select(NotePageContentDO).where(
                        NotePageContentDO.file_id == file_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(current_pages) == len(pages)


TEST_DATA_DIR = Path(__file__).parents[3] / "testdata"


@pytest.mark.parametrize(
    ("relative_note_path", "expected_hashes"),
    [
        (
            "20251207_221454.note",
            ["8222bb495f9987c137b49585ae75a912"],
        ),
        (
            "dsummersl/sn2md_20260618.note",
            ["ff9877eb19672f85d036ddfcd99e5ada"],
        ),
        (
            "mmujynya/stroller.note",
            [
                "3bfafc2b307510c90ecbccd38800093f",
                "f214521188a21f0d91f5f883aa5af07c",
            ],
        ),
        (
            "philips/manta.note",
            ["af7e28b961de2109dc35b248f5a4c4dc"],
        ),
    ],
)
async def test_page_hashing_preserves_pinned_wire_md5(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    relative_note_path: str,
    expected_hashes: list[str],
) -> None:
    """Verify page content_hash stays bit-for-bit identical across .note variants."""
    note_path = TEST_DATA_DIR / relative_note_path
    file_id = 1000
    storage_key = f"pinned_hash_{note_path.stem}"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=1,
                storage_key=storage_key,
                file_name=note_path.name,
                directory_id=0,
            )
        )
        await session.commit()

    assert await page_hashing_module.run(file_id, session_manager) is True

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert [row.content_hash for row in rows] == expected_hashes


async def test_page_hashing_marks_task_failed_on_missing_or_corrupt_file(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    missing_file_id = 1001
    corrupt_file_id = 1002
    await blob_storage.put(USER_DATA_BUCKET, "corrupt_key", b"not a valid .note file")

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=missing_file_id,
                    user_id=1,
                    storage_key="missing_key",
                    file_name="missing.note",
                    directory_id=0,
                ),
                UserFileDO(
                    id=corrupt_file_id,
                    user_id=1,
                    storage_key="corrupt_key",
                    file_name="corrupt.note",
                    directory_id=0,
                ),
            ]
        )
        await session.commit()

    for fid in (missing_file_id, corrupt_file_id):
        assert await page_hashing_module.run(fid, session_manager) is False
        async with session_manager.session() as session:
            task = (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == fid)
                    .where(SystemTaskDO.task_type == "HASHING")
                )
            ).scalar_one()
            assert task.status == "FAILED"
            assert task.last_error is not None
