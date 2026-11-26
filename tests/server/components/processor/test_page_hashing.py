from pathlib import Path

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.orm import undefer

from supernote.server.components.processor.page_hashing import (
    PageHashingModule,
)
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NotePagesDeltaEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService


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
    await page_hashing_module.run(file_id, session_manager, user_id=user_id)

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
        assert task.data == "v3"

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
            user_id=user_id,
            file_id=file_id,
            task_type="OCR_EXTRACTION",
            key=f"page_{page.page_id}",
            status="COMPLETED",
        )
        summary_task = SystemTaskDO(
            user_id=user_id,
            file_id=file_id,
            task_type="SUMMARY_GENERATION",
            key="global",
            status="COMPLETED",
        )
        downstream_global_task = SystemTaskDO(
            user_id=user_id,
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
                    .options(undefer(NotePageContentDO.previous_text))
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
        # Prior text_content moves to previous_text while text_content, embedding, and embedding_model reset to None.
        assert page.text_content is None
        assert page.previous_text == "dummy_ocr"
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
    assert page_hashing_module.file_service.event_bus is not None
    delta_events: list[NotePagesDeltaEvent] = []

    async def on_delta(ev: NotePagesDeltaEvent) -> None:
        delta_events.append(ev)

    page_hashing_module.file_service.event_bus.subscribe(
        NotePagesDeltaEvent, on_delta, inline=True
    )

    async with session_manager.session() as session:
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id,
                    page_index=extra_page_index,
                    page_id="trash_id",
                    content_hash="trash",
                    text_content="- [ ] Deleted page task",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=extra_page_index + 1,
                    page_id="trash_untranscribed",
                    content_hash="trash2",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    # Run process again
    await page_hashing_module.process(file_id, session_manager)

    assert len(delta_events) == 1
    assert delta_events[0].to_payload() == {
        "file_id": str(file_id),
        "file_path": "real.note",
        "added_pages": [],
        "modified_pages": [],
        "moved_pages": [],
        "deleted_pages": ["trash_id", "trash_untranscribed"],
        "deleted_page_texts": {"trash_id": "- [ ] Deleted page task"},
    }

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

    assert await page_hashing_module.run(file_id, session_manager, user_id=1) is True

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
        assert await page_hashing_module.run(fid, session_manager, user_id=1) is False
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


async def test_page_hashing_skips_missing_or_inactive_file_without_task_row(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
) -> None:
    """Missing, soft-deleted, or storage-keyless files skip hashing with no SystemTaskDO row."""
    missing_file_id = 1091
    inactive_file_id = 1092
    empty_key_file_id = 1093

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=inactive_file_id,
                    user_id=1,
                    storage_key="inactive_key",
                    file_name="inactive.note",
                    directory_id=0,
                    is_active="N",
                ),
                UserFileDO(
                    id=empty_key_file_id,
                    user_id=1,
                    storage_key="",
                    file_name="empty.note",
                    directory_id=0,
                    is_active="Y",
                ),
            ]
        )
        await session.commit()

    for fid in (missing_file_id, inactive_file_id, empty_key_file_id):
        assert await page_hashing_module.run(fid, session_manager, user_id=1) is True
        async with session_manager.session() as session:
            tasks = (
                (
                    await session.execute(
                        select(SystemTaskDO).where(SystemTaskDO.file_id == fid)
                    )
                )
                .scalars()
                .all()
            )
            assert tasks == []


async def _seed_user_note_file(
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    *,
    user_id: int,
    file_id: int,
    note_path: Path,
) -> None:
    storage_key = f"note_{file_id}_{note_path.stem}"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name=note_path.name,
                directory_id=0,
            )
        )
        await session.commit()


def _page_diff_snapshot() -> dict[str, float]:
    change_types = ("added", "modified", "moved", "unchanged", "deleted")
    return {
        ct: (
            REGISTRY.get_sample_value(
                "supernote_note_pages_parsed_total",
                {"change_type": ct},
            )
            or 0.0
        )
        for ct in change_types
    }


def _assert_page_diff_delta(
    before_counts: dict[str, float],
    after_counts: dict[str, float],
    *,
    added: float = 0.0,
    modified: float = 0.0,
    moved: float = 0.0,
    unchanged: float = 0.0,
    deleted: float = 0.0,
) -> None:
    assert after_counts["added"] - before_counts["added"] == added
    assert after_counts["modified"] - before_counts["modified"] == modified
    assert after_counts["moved"] - before_counts["moved"] == moved
    assert after_counts["unchanged"] - before_counts["unchanged"] == unchanged
    assert after_counts["deleted"] - before_counts["deleted"] == deleted


async def test_page_hashing_emits_mutually_exclusive_page_diff_metrics(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify PageHashingModule emits exact page-diff counters for standard notes."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1040, note_path=note_path
    )

    # Initial 3-page standard `<PAGEID>` parse -> 3 added.
    snap = _page_diff_snapshot()
    assert await page_hashing_module.run(1040, session_manager, user_id=7) is True
    snap_after_init = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap,
        snap_after_init,
        added=3.0,
    )

    # Simulate: page 0 moved + modified, page 1 moved only, page 2 unchanged, 1 deleted page.
    async with session_manager.session() as session:
        rows = list(
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == 1040)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 3
        rows[0].page_index = 1
        rows[0].content_hash = "stale_hash"
        rows[1].page_index = 0
        session.add(
            NotePageContentDO(
                file_id=1040,
                page_index=9,
                page_id="deleted_pid",
                content_hash="deleted_hash",
            )
        )
        await session.commit()

    assert await page_hashing_module.run(1040, session_manager, user_id=7) is True
    snap_after_reconcile = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_after_init,
        snap_after_reconcile,
        modified=1.0,
        moved=1.0,
        unchanged=1.0,
        deleted=1.0,
    )


async def test_page_hashing_preserves_previous_text_across_double_edit_and_blank_edit(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify repeated hash invalidation before OCR preserves previous_text, while blank '' becomes None."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1050, note_path=note_path
    )
    assert await page_hashing_module.run(1050, session_manager, user_id=7) is True

    async with session_manager.session() as session:
        rows = list(
            (
                await session.execute(
                    select(NotePageContentDO)
                    .options(undefer(NotePageContentDO.previous_text))
                    .where(NotePageContentDO.file_id == 1050)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        rows[0].text_content = "• First version"
        rows[0].content_hash = "stale_v1"
        rows[1].text_content = ""
        rows[1].content_hash = "stale_blank"
        await session.commit()

    # First invalidation: page 0 moves text_content -> previous_text; blank page 1 sets previous_text=None.
    await page_hashing_module.process(1050, session_manager)

    # Simulate a second edit arriving before OCR runs for page 0.
    async with session_manager.session() as session:
        p0 = (
            await session.execute(
                select(NotePageContentDO)
                .options(undefer(NotePageContentDO.previous_text))
                .where(NotePageContentDO.file_id == 1050)
                .where(NotePageContentDO.page_index == 0)
            )
        ).scalar_one()
        assert p0.text_content is None
        assert p0.previous_text == "• First version"
        p0.content_hash = "stale_v2"
        await session.commit()

    await page_hashing_module.process(1050, session_manager)

    async with session_manager.session() as session:
        rows = list(
            (
                await session.execute(
                    select(NotePageContentDO)
                    .options(undefer(NotePageContentDO.previous_text))
                    .where(NotePageContentDO.file_id == 1050)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert rows[0].text_content is None
        assert rows[0].previous_text == "• First version"
        assert rows[1].text_content is None
        assert rows[1].previous_text is None


async def test_page_hashing_deleted_page_texts_falls_back_to_previous_text_and_skips_blank(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify deleted_page_texts falls back to previous_text when OCR is pending and omits blank pages."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1051, note_path=note_path
    )
    assert await page_hashing_module.run(1051, session_manager, user_id=7) is True

    assert page_hashing_module.file_service.event_bus is not None
    delta_events: list[NotePagesDeltaEvent] = []

    async def on_delta(ev: NotePagesDeltaEvent) -> None:
        delta_events.append(ev)

    page_hashing_module.file_service.event_bus.subscribe(
        NotePagesDeltaEvent, on_delta, inline=True
    )

    async with session_manager.session() as session:
        session.add_all(
            [
                NotePageContentDO(
                    file_id=1051,
                    page_index=10,
                    page_id="edited_then_deleted",
                    content_hash="h_ed",
                    text_content=None,
                    previous_text="• Pending OCR task",
                ),
                NotePageContentDO(
                    file_id=1051,
                    page_index=11,
                    page_id="blank_deleted",
                    content_hash="h_bl",
                    text_content="",
                ),
            ]
        )
        await session.commit()

    await page_hashing_module.process(1051, session_manager)

    assert len(delta_events) == 1
    assert delta_events[0].to_payload() == {
        "file_id": "1051",
        "file_path": "A5X_TestNote_With_Pdf_Template.note",
        "added_pages": [],
        "modified_pages": [],
        "moved_pages": [],
        "deleted_pages": ["edited_then_deleted", "blank_deleted"],
        "deleted_page_texts": {"edited_then_deleted": "• Pending OCR task"},
    }
