"""Unit tests for `supernote.server.components.note_metadata.processor`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import exists, func, select

from supernote.models.base import TaskType
from supernote.notebook import Title, load
from supernote.server.components.note_metadata.processor import (
    NoteMetadataModule,
    _title_reading_order,
    async_setup_processor,
)
from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageMetadataDO,
    NoteTitleDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.utils.paths import get_title_png_path

TEST_DATA_DIR = Path(__file__).parents[3] / "testdata"


@pytest.fixture
def note_metadata_module(file_service: FileService) -> NoteMetadataModule:
    return NoteMetadataModule(file_service=file_service)


async def test_async_setup_processor_registers_note_metadata_module(
    component_core: ServerCore,
) -> None:
    registrar = ProcessorRegistrar()
    await async_setup_processor(component_core, registrar)
    assert [m.task_type for m in registrar.modules] == [TaskType.NOTE_METADATA]


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


async def test_note_metadata_persists_note_and_page_metadata(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify NoteMetadataModule populates NoteMetadataDO and per-page NotePageMetadataDO."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1010, note_path=note_path
    )

    assert await note_metadata_module.run(1010, session_manager, user_id=7) is True

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
        assert all(len(r.content_hash) == 32 for r in page_metas)
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


async def test_note_metadata_persists_page_metadata_for_legacy_note_without_page_id(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify legacy notes lacking <PAGEID> still persist NotePageMetadataDO and wire hashes."""
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1011, note_path=legacy_path
    )

    assert await note_metadata_module.run(1011, session_manager, user_id=7) is True

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


async def test_note_metadata_skips_unchanged_pages_on_rehash(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify re-hashing decodes bitmaps and updates rows only for pages whose hash changed."""
    note_path = TEST_DATA_DIR / "nelinory" / "A5X_TestNote_With_Pdf_Template.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1012, note_path=note_path
    )
    assert await note_metadata_module.run(1012, session_manager, user_id=7) is True

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

        await session.commit()

    with patch(
        "supernote.server.components.note_metadata.processor.load",
        wraps=load,
    ) as mock_load:
        assert await note_metadata_module.run(1012, session_manager, user_id=7) is True
        assert [call.kwargs["page_number"] for call in mock_load.call_args_list] == [1]

        mock_load.reset_mock()
        assert await note_metadata_module.run(1012, session_manager, user_id=7) is True
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


async def test_note_metadata_updates_annotations_without_loading_bitmaps_when_hash_cached(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify footer annotation changes update NotePageMetadataDO without decoding bitmaps when content_hash is cached."""
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1014, note_path=legacy_path
    )
    assert await note_metadata_module.run(1014, session_manager, user_id=7) is True

    async with session_manager.session() as session:
        pm_0 = await session.get(NotePageMetadataDO, (7, 1014, 0))
        assert pm_0 is not None
        expected_keywords_json = pm_0.keywords_json
        assert json.loads(expected_keywords_json) != []
        pm_0.keywords_json = "[]"
        await session.commit()

    with patch(
        "supernote.server.components.note_metadata.processor.load",
        wraps=load,
    ) as mock_load:
        assert await note_metadata_module.run(1014, session_manager, user_id=7) is True
        mock_load.assert_not_called()

    async with session_manager.session() as session:
        refreshed_0 = await session.get(NotePageMetadataDO, (7, 1014, 0))
        assert refreshed_0 is not None
        assert refreshed_0.keywords_json == expected_keywords_json


async def test_note_metadata_prunes_stale_page_metadata_when_page_count_shrinks(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """Verify trailing NotePageMetadataDO rows beyond total_pages are removed on re-hash."""
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1013, note_path=test_note_path
    )
    assert await note_metadata_module.run(1013, session_manager, user_id=7) is True

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

    assert await note_metadata_module.run(1013, session_manager, user_id=7) is True

    async with session_manager.session() as session:
        assert await session.get(NotePageMetadataDO, (7, 1013, stale_index)) is None


async def test_note_metadata_cleanup_file_deletes_note_and_page_metadata(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify cleanup_file removes rows only for target (user_id, file_id)."""
    async with session_manager.session() as session:
        session.add_all(
            [
                NoteMetadataDO(
                    user_id=7, file_id=1020, file_type="note", total_pages=1
                ),
                NotePageMetadataDO(user_id=7, file_id=1020, page_index=0, page_id="p0"),
                NoteTitleDO(user_id=7, file_id=1020, title_index=0, page_index=0),
                # Same file_id owned by a different user must remain untouched.
                NoteMetadataDO(
                    user_id=8, file_id=1020, file_type="note", total_pages=1
                ),
                NotePageMetadataDO(user_id=8, file_id=1020, page_index=0, page_id="p0"),
                NoteTitleDO(user_id=8, file_id=1020, title_index=0, page_index=0),
                # Different file_id owned by the same user must remain untouched.
                NoteMetadataDO(
                    user_id=7, file_id=1021, file_type="note", total_pages=1
                ),
                NotePageMetadataDO(user_id=7, file_id=1021, page_index=0, page_id="p0"),
                NoteTitleDO(user_id=7, file_id=1021, title_index=0, page_index=0),
            ]
        )
        await session.commit()

    await note_metadata_module.cleanup_file(
        file_id=1020, user_id=7, session_manager=session_manager
    )

    async with session_manager.session() as session:
        assert await session.get(NoteMetadataDO, (7, 1020)) is None
        assert await session.get(NotePageMetadataDO, (7, 1020, 0)) is None
        assert await session.get(NoteTitleDO, (7, 1020, 0)) is None
        assert await session.get(NoteMetadataDO, (8, 1020)) is not None
        assert await session.get(NotePageMetadataDO, (8, 1020, 0)) is not None
        assert await session.get(NoteTitleDO, (8, 1020, 0)) is not None
        assert await session.get(NoteMetadataDO, (7, 1021)) is not None
        assert await session.get(NotePageMetadataDO, (7, 1021, 0)) is not None
        assert await session.get(NoteTitleDO, (7, 1021, 0)) is not None


HEADING_NOTE_PATH = (
    TEST_DATA_DIR / "philips" / "heading-n5-20260016-backgrounds-marker.note"
)
HEADING_TITLE_MD5S = [
    "4f60eac0ba701b4983269a55649430ad",
    "b094a9f71c442cf2a0544d737603b0dc",
    "f14caee340e90ceab17cad156682ca9c",
    "63bcfe0053116378ededa5038ba7e389",
]


async def _title_rows(
    session_manager: DatabaseSessionManager, file_id: int
) -> list[NoteTitleDO]:
    async with session_manager.session() as session:
        return list(
            (
                await session.execute(
                    select(NoteTitleDO)
                    .where(NoteTitleDO.file_id == file_id)
                    .order_by(NoteTitleDO.title_index)
                )
            )
            .scalars()
            .all()
        )


async def _hash_heading_note(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    file_id: int,
) -> None:
    await _seed_user_note_file(
        session_manager,
        blob_storage,
        user_id=7,
        file_id=file_id,
        note_path=HEADING_NOTE_PATH,
    )
    assert await note_metadata_module.run(file_id, session_manager, user_id=7) is True


def _title(page: int, left: int, top: int) -> Title:
    return Title({"TITLERECT": f"{left},{top},10,10"}, page_number=page)


def test_title_reading_order_sorts_by_page_then_top_then_left() -> None:
    titles = [
        _title(page=1, left=0, top=0),
        _title(page=0, left=50, top=100),
        _title(page=0, left=10, top=100),
        _title(page=0, left=90, top=20),
    ]
    assert [
        _title_reading_order(t) for t in sorted(titles, key=_title_reading_order)
    ] == [(0, 20, 90), (0, 100, 10), (0, 100, 50), (1, 0, 0)]


async def test_note_metadata_persists_titles_in_reading_order(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    await _hash_heading_note(note_metadata_module, session_manager, blob_storage, 1060)

    rows = await _title_rows(session_manager, 1060)
    assert [
        (
            r.title_index,
            r.page_index,
            r.rect,
            r.level,
            r.style,
            r.bitmap_md5,
        )
        for r in rows
    ] == [
        (0, 1, [500, 329, 356, 148], 1, "1000254", HEADING_TITLE_MD5S[0]),
        (1, 1, [480, 691, 582, 178], 2, "1157254", HEADING_TITLE_MD5S[1]),
        (2, 1, [490, 1016, 284, 125], 3, "1201000", HEADING_TITLE_MD5S[2]),
        (3, 1, [508, 1295, 290, 118], 4, "1000000", HEADING_TITLE_MD5S[3]),
    ]


async def test_note_metadata_deletes_stale_title_rows(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    await _hash_heading_note(note_metadata_module, session_manager, blob_storage, 1064)
    async with session_manager.session() as session:
        session.add(NoteTitleDO(user_id=7, file_id=1064, title_index=4, page_index=2))
        await session.commit()

    assert await note_metadata_module.run(1064, session_manager, user_id=7) is True

    rows = await _title_rows(session_manager, 1064)
    assert [r.title_index for r in rows] == [0, 1, 2, 3]


async def test_note_metadata_deletes_crop_of_redrawn_title(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    await _hash_heading_note(note_metadata_module, session_manager, blob_storage, 1065)
    previous_md5 = "a" * 32
    async with session_manager.session() as session:
        row_1 = await session.get(NoteTitleDO, (7, 1065, 1))
        assert row_1 is not None
        row_1.bitmap_md5 = previous_md5
        await session.commit()
    current_key = get_title_png_path(1065, HEADING_TITLE_MD5S[0])
    previous_key = get_title_png_path(1065, previous_md5)
    await blob_storage.put(CACHE_BUCKET, current_key, b"png")
    await blob_storage.put(CACHE_BUCKET, previous_key, b"png")

    assert await note_metadata_module.run(1065, session_manager, user_id=7) is True

    assert await blob_storage.exists(CACHE_BUCKET, current_key)
    assert not await blob_storage.exists(CACHE_BUCKET, previous_key)


async def test_note_metadata_cleanup_file_deletes_title_crops(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    purged_key = get_title_png_path(1066, "a" * 32)
    kept_key = get_title_png_path(1067, "a" * 32)
    await blob_storage.put(CACHE_BUCKET, purged_key, b"png")
    await blob_storage.put(CACHE_BUCKET, kept_key, b"png")

    await note_metadata_module.cleanup_file(
        file_id=1066, user_id=7, session_manager=session_manager
    )

    assert not await blob_storage.exists(CACHE_BUCKET, purged_key)
    assert await blob_storage.exists(CACHE_BUCKET, kept_key)


async def test_note_metadata_skips_unchanged_title_rows_on_rehash(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    await _hash_heading_note(note_metadata_module, session_manager, blob_storage, 1062)
    async with session_manager.session() as session:
        row_0 = await session.get(NoteTitleDO, (7, 1062, 0))
        assert row_0 is not None
        row_0.update_time = 12345
        await session.commit()

    assert await note_metadata_module.run(1062, session_manager, user_id=7) is True

    async with session_manager.session() as session:
        refreshed = await session.get(NoteTitleDO, (7, 1062, 0))
        assert refreshed is not None
        assert refreshed.update_time == 12345


async def test_note_metadata_supports_sql_json_extract_queries(
    note_metadata_module: NoteMetadataModule,
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
        assert await note_metadata_module.run(fid, session_manager, user_id=7) is True

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


async def test_note_metadata_emits_legacy_page_diff_metrics(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify NoteMetadataModule emits page-diff counters for legacy notes lacking `<PAGEID>`."""
    legacy_path = TEST_DATA_DIR / "philips" / "test.note"
    await _seed_user_note_file(
        session_manager, blob_storage, user_id=7, file_id=1041, note_path=legacy_path
    )

    snap_before = _page_diff_snapshot()
    assert await note_metadata_module.run(1041, session_manager, user_id=7) is True
    snap_legacy_init = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_before,
        snap_legacy_init,
        added=2.0,
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

    assert await note_metadata_module.run(1041, session_manager, user_id=7) is True
    snap_legacy_rehash = _page_diff_snapshot()
    _assert_page_diff_delta(
        snap_legacy_init,
        snap_legacy_rehash,
        modified=1.0,
        unchanged=1.0,
        deleted=1.0,
    )


async def test_note_metadata_skips_standalone_image(
    note_metadata_module: NoteMetadataModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Standalone images (non-.note files) should be skipped by run_if_needed()."""
    await blob_storage.put(USER_DATA_BUCKET, "photo_key", b"\x89PNG\r\n\x1a\n")
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=1050,
                user_id=7,
                storage_key="photo_key",
                file_name="sketch.png",
                directory_id=0,
            )
        )
        await session.commit()

    assert (
        await note_metadata_module.run_if_needed(1050, session_manager, user_id=7)
        is False
    )
    assert await note_metadata_module.run(1050, session_manager, user_id=7) is True

    async with session_manager.session() as session:
        assert await session.get(NoteMetadataDO, (7, 1050)) is None
