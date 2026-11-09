import json
from pathlib import Path
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import exists, func, select

from supernote.notebook import load
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
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
        assert task.data == "v2"

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


async def test_page_hashing_persists_note_and_page_metadata(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify PageHashingModule populates NoteMetadataDO and per-page NotePageMetadataDO."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1010, note_path=note_path
    )

    assert await page_hashing_module.run(1010, session_manager) is True

    async with session_manager.session() as session:
        meta = await session.get(NoteMetadataDO, (7, 1010))
        assert meta is not None
        assert meta.file_type == "note"
        assert meta.total_pages == 3
        assert json.loads(meta.header_json)["APPLY_EQUIPMENT"] == "A5X"
        assert "PAGE1" in json.loads(meta.footer_json)

        page_metas = list(
            (
                await session.execute(
                    select(NotePageMetadataDO)
                    .where(NotePageMetadataDO.file_id == 1010)
                    .order_by(NotePageMetadataDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        content_rows = list(
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == 1010)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert [r.content_hash for r in page_metas] == [
            c.content_hash for c in content_rows
        ]
        assert [
            (r.page_index, r.page_style, r.has_ink, r.has_drawables) for r in page_metas
        ] == [
            (0, "user_pdf_Pdf_Template_1", True, True),
            (1, "user_pdf_Pdf_Template_2", False, False),
            (2, "user_pdf_Pdf_Template_3", True, True),
        ]
        assert json.loads(page_metas[0].page_json)["PAGESTYLE"] == (
            "user_pdf_Pdf_Template_1"
        )


async def test_page_hashing_persists_page_metadata_for_legacy_note_without_page_id(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify legacy notes lacking <PAGEID> still persist NotePageMetadataDO and wire hashes."""
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1011, note_path=legacy_path
    )

    assert await page_hashing_module.run(1011, session_manager) is True

    async with session_manager.session() as session:
        legacy_pages = list(
            (
                await session.execute(
                    select(NotePageMetadataDO)
                    .where(NotePageMetadataDO.file_id == 1011)
                    .order_by(NotePageMetadataDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        assert len(legacy_pages) == 2
        assert legacy_pages[0].page_id == ""
        assert len(legacy_pages[0].content_hash) == 32
        assert legacy_pages[0].has_ink is True
        assert legacy_pages[0].has_drawables is True
        kw_wire = json.loads(legacy_pages[0].keywords_json)
        assert isinstance(kw_wire, list) and len(kw_wire) >= 1
        assert "KEYWORD" in kw_wire[0]


async def test_page_hashing_skips_unchanged_pages_on_rehash(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify re-hashing decodes bitmaps and updates rows only for pages whose hash changed."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1012, note_path=note_path
    )
    assert await page_hashing_module.run(1012, session_manager) is True

    async with session_manager.session() as session:
        meta_0 = await session.get(NotePageMetadataDO, (7, 1012, 0))
        meta_1 = await session.get(NotePageMetadataDO, (7, 1012, 1))
        meta_2 = await session.get(NotePageMetadataDO, (7, 1012, 2))
        assert meta_0 is not None and meta_1 is not None and meta_2 is not None
        original_hash_1 = meta_1.content_hash

        # Pin sentinel timestamps on unchanged pages and invalidate only page 1's hash.
        meta_0.update_time = 12345
        meta_2.update_time = 12345
        meta_1.content_hash = "stale_hash"
        meta_1.has_ink = True

        content_0 = (
            await session.execute(
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == 1012)
                .where(NotePageContentDO.page_index == 0)
            )
        ).scalar_one()
        content_0.text_content = "preserved ocr"
        await session.commit()

    with patch(
        "supernote.server.services.processor_modules.page_hashing.load",
        wraps=load,
    ) as mock_load:
        assert await page_hashing_module.run(1012, session_manager) is True
        assert [call.kwargs["page_number"] for call in mock_load.call_args_list] == [1]

        mock_load.reset_mock()
        assert await page_hashing_module.run(1012, session_manager) is True
        mock_load.assert_not_called()

    async with session_manager.session() as session:
        refreshed_0 = await session.get(NotePageMetadataDO, (7, 1012, 0))
        refreshed_1 = await session.get(NotePageMetadataDO, (7, 1012, 1))
        refreshed_2 = await session.get(NotePageMetadataDO, (7, 1012, 2))
        assert (
            refreshed_0 is not None
            and refreshed_1 is not None
            and refreshed_2 is not None
        )
        assert refreshed_0.update_time == 12345
        assert refreshed_2.update_time == 12345
        assert refreshed_1.content_hash == original_hash_1
        assert refreshed_1.has_ink is False

        refreshed_content_0 = (
            await session.execute(
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == 1012)
                .where(NotePageContentDO.page_index == 0)
            )
        ).scalar_one()
        assert refreshed_content_0.text_content == "preserved ocr"


async def test_page_hashing_updates_annotations_without_loading_bitmaps_when_hash_cached(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify footer annotation changes update NotePageMetadataDO without decoding bitmaps when content_hash is cached."""
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1014, note_path=legacy_path
    )
    assert await page_hashing_module.run(1014, session_manager) is True

    async with session_manager.session() as session:
        pm_0 = await session.get(NotePageMetadataDO, (7, 1014, 0))
        assert pm_0 is not None
        expected_keywords_json = pm_0.keywords_json
        assert json.loads(expected_keywords_json) != []
        pm_0.keywords_json = "[]"
        await session.commit()

    with patch(
        "supernote.server.services.processor_modules.page_hashing.load",
        wraps=load,
    ) as mock_load:
        assert await page_hashing_module.run(1014, session_manager) is True
        mock_load.assert_not_called()

    async with session_manager.session() as session:
        refreshed_0 = await session.get(NotePageMetadataDO, (7, 1014, 0))
        assert refreshed_0 is not None
        assert refreshed_0.keywords_json == expected_keywords_json


async def test_page_hashing_prunes_stale_page_metadata_when_page_count_shrinks(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """Verify trailing NotePageMetadataDO rows beyond total_pages are removed on re-hash."""
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1013, note_path=test_note_path
    )
    assert await page_hashing_module.run(1013, session_manager) is True

    async with session_manager.session() as session:
        meta = await session.get(NoteMetadataDO, (7, 1013))
        assert meta is not None
        stale_index = meta.total_pages + 3
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=1013,
                page_index=stale_index,
                page_id="stale_page_id",
            )
        )
        await session.commit()

    assert await page_hashing_module.run(1013, session_manager) is True

    async with session_manager.session() as session:
        assert await session.get(NotePageMetadataDO, (7, 1013, stale_index)) is None


async def test_page_hashing_cleanup_file_deletes_note_and_page_metadata(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify cleanup_file removes NoteMetadataDO and NotePageMetadataDO only for target file_id."""
    async with session_manager.session() as session:
        session.add_all(
            [
                NoteMetadataDO(
                    user_id=7, file_id=1020, file_type="note", total_pages=1
                ),
                NotePageMetadataDO(user_id=7, file_id=1020, page_index=0, page_id="p0"),
                NoteMetadataDO(
                    user_id=7, file_id=1021, file_type="note", total_pages=1
                ),
                NotePageMetadataDO(user_id=7, file_id=1021, page_index=0, page_id="p0"),
            ]
        )
        await session.commit()

    await page_hashing_module.cleanup_file(
        file_id=1020, user_id=7, session_manager=session_manager
    )

    async with session_manager.session() as session:
        assert await session.get(NoteMetadataDO, (7, 1020)) is None
        assert await session.get(NotePageMetadataDO, (7, 1020, 0)) is None
        assert await session.get(NoteMetadataDO, (7, 1021)) is not None
        assert await session.get(NotePageMetadataDO, (7, 1021, 0)) is not None


async def test_page_hashing_metadata_supports_sql_json_extract_queries(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify persisted header_json, page_json, and keywords_json can be queried via SQL json_extract/json_each."""
    notes = [
        (1030, TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"),
        (1031, TEST_DATA_DIR / "philips" / "manta.note"),
        (1032, TEST_DATA_DIR / "philips" / "test.note"),
    ]
    for fid, path in notes:
        await _seed_user_note_file(
            session_manager, blob_storage, user_id=7, file_id=fid, note_path=path
        )
        assert await page_hashing_module.run(fid, session_manager) is True

    async with session_manager.session() as session:
        manta_meta = await session.get(NoteMetadataDO, (7, 1031))
        assert manta_meta is not None
        assert json.loads(manta_meta.header_json)["APPLY_EQUIPMENT"] == "N5"

        # Query notebook header_json via SQL json_extract (e.g. filter by equipment).
        n5_file_ids = list(
            (
                await session.execute(
                    select(NoteMetadataDO.file_id).where(
                        NoteMetadataDO.user_id == 7,
                        func.json_extract(
                            NoteMetadataDO.header_json, "$.APPLY_EQUIPMENT"
                        )
                        == "N5",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert n5_file_ids == [1031]

        # Query page_json via SQL json_extract (e.g. filter by custom template PAGESTYLEMD5).
        matching_template_pages = [
            (row.file_id, row.page_index)
            for row in (
                await session.execute(
                    select(
                        NotePageMetadataDO.file_id,
                        NotePageMetadataDO.page_index,
                    ).where(
                        NotePageMetadataDO.user_id == 7,
                        func.json_extract(
                            NotePageMetadataDO.page_json, "$.PAGESTYLEMD5"
                        )
                        == "ceba6dbd269b88f41a82eecc37266baa_9954",
                    )
                )
            ).all()
        ]
        assert matching_template_pages == [(1030, 0)]

        # Query JSON array elements in keywords_json via SQL json_each + json_extract.
        kw_entry = func.json_each(NotePageMetadataDO.keywords_json).table_valued(
            "value"
        )
        keyword_pages = [
            (row.file_id, row.page_index)
            for row in (
                await session.execute(
                    select(
                        NotePageMetadataDO.file_id,
                        NotePageMetadataDO.page_index,
                    ).where(
                        NotePageMetadataDO.user_id == 7,
                        exists(
                            select(1)
                            .select_from(kw_entry)
                            .where(
                                func.json_extract(kw_entry.c.value, "$.KEYWORD")
                                == "dummy"
                            )
                        ),
                    )
                )
            ).all()
        ]
        assert keyword_pages == [(1032, 0)]


def _page_diff_snapshot() -> tuple[dict[str, float], float, float]:
    change_types = ("added", "modified", "moved", "unchanged", "deleted")
    counts = {
        ct: (
            REGISTRY.get_sample_value(
                "supernote_note_pages_parsed_total",
                {"change_type": ct},
            )
            or 0.0
        )
        for ct in change_types
    }
    total_sum = (
        REGISTRY.get_sample_value(
            "supernote_note_pages_per_run_sum",
            {"scope": "total"},
        )
        or 0.0
    )
    dirty_sum = (
        REGISTRY.get_sample_value(
            "supernote_note_pages_per_run_sum",
            {"scope": "dirty"},
        )
        or 0.0
    )
    return counts, total_sum, dirty_sum


def _assert_page_diff_delta(
    before: tuple[dict[str, float], float, float],
    after: tuple[dict[str, float], float, float],
    *,
    added: float = 0.0,
    modified: float = 0.0,
    moved: float = 0.0,
    unchanged: float = 0.0,
    deleted: float = 0.0,
    total_sum: float,
    dirty_sum: float,
) -> None:
    before_counts, before_total, before_dirty = before
    after_counts, after_total, after_dirty = after
    assert after_counts["added"] - before_counts["added"] == added
    assert after_counts["modified"] - before_counts["modified"] == modified
    assert after_counts["moved"] - before_counts["moved"] == moved
    assert after_counts["unchanged"] - before_counts["unchanged"] == unchanged
    assert after_counts["deleted"] - before_counts["deleted"] == deleted
    assert after_total - before_total == total_sum
    assert after_dirty - before_dirty == dirty_sum


async def test_page_hashing_emits_mutually_exclusive_page_diff_metrics(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify PageHashingModule emits exact page-diff counters and histograms for standard and legacy notes."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1040, note_path=note_path
    )

    # 1. Initial 3-page standard `<PAGEID>` parse -> 3 added, total=3, dirty=3.
    snap = _page_diff_snapshot()
    assert await page_hashing_module.run(1040, session_manager) is True
    snap_after_init = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap,
        snap_after_init,
        added=3.0,
        total_sum=3.0,
        dirty_sum=3.0,
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

    assert await page_hashing_module.run(1040, session_manager) is True
    snap_after_reconcile = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_after_init,
        snap_after_reconcile,
        modified=1.0,
        moved=1.0,
        unchanged=1.0,
        deleted=1.0,
        total_sum=3.0,
        dirty_sum=1.0,
    )

    # 2. Legacy 2-page `.note` lacking `<PAGEID>`: initial parse + modified/unchanged/deleted re-hash.
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1041, note_path=legacy_path
    )

    assert await page_hashing_module.run(1041, session_manager) is True
    snap_legacy_init = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_after_reconcile,
        snap_legacy_init,
        added=2.0,
        total_sum=2.0,
        dirty_sum=2.0,
    )

    async with session_manager.session() as session:
        pm_0 = await session.get(NotePageMetadataDO, (7, 1041, 0))
        assert pm_0 is not None
        pm_0.content_hash = "stale_legacy_hash"
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=1041,
                page_index=5,
                page_id="",
                content_hash="deleted_legacy_hash",
            )
        )
        await session.commit()

    assert await page_hashing_module.run(1041, session_manager) is True
    snap_legacy_rehash = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_legacy_init,
        snap_legacy_rehash,
        modified=1.0,
        unchanged=1.0,
        deleted=1.0,
        total_sum=2.0,
        dirty_sum=1.0,
    )
