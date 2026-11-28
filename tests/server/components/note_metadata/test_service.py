"""Unit tests for `supernote.server.components.note_metadata.service`."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from supernote.notebook import fileformat
from supernote.notebook.converter import ImageConverter
from supernote.notebook.exceptions import DecoderException
from supernote.server.components.note_metadata import NoteMetadataService
from supernote.server.components.note_metadata.processor import NoteMetadataModule
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NoteTitleDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.utils.paths import get_title_png_path

HEADING_NOTE_PATH = (
    Path(__file__).parents[3]
    / "testdata"
    / "philips"
    / "heading-n5-20260016-backgrounds-marker.note"
)
BLACK_TITLE_MD5 = "4f60eac0ba701b4983269a55649430ad"
DARK_GREY_TITLE_MD5 = "b094a9f71c442cf2a0544d737603b0dc"


@pytest.fixture
def note_metadata_service(
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> NoteMetadataService:
    return NoteMetadataService(
        session_manager=session_manager,
        blob_storage=blob_storage,
    )


async def _hash_heading_note(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    *,
    user_id: int,
    file_id: int,
) -> None:
    storage_key = f"headings_{file_id}"
    await file_service.blob_storage.put(
        USER_DATA_BUCKET, storage_key, HEADING_NOTE_PATH.read_bytes()
    )
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="Headings.note",
                directory_id=0,
            )
        )
        await session.commit()
    metadata_mod = NoteMetadataModule(file_service=file_service)
    assert await metadata_mod.run(file_id, session_manager, user_id=user_id) is True


async def _read_cache(file_service: FileService, key: str) -> bytes:
    return b"".join(
        [chunk async for chunk in file_service.blob_storage.get(CACHE_BUCKET, key)]
    )


async def test_get_title_png_key_renders_crop_on_cache_miss(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8401
    )

    key = await note_metadata_service.get_title_png_key(
        user_id=test_user_id, file_id=8401, bitmap_md5=BLACK_TITLE_MD5
    )

    assert key == get_title_png_path(8401, BLACK_TITLE_MD5)
    png = await _read_cache(file_service, key)
    assert Image.open(io.BytesIO(png)).size == (356, 148)


async def test_get_title_png_key_caches_every_crop_from_one_render(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8403
    )
    assert await note_metadata_service.get_title_png_key(
        user_id=test_user_id, file_id=8403, bitmap_md5=BLACK_TITLE_MD5
    )

    with patch(
        "supernote.server.components.note_metadata.service._render_title_pngs"
    ) as mock_render:
        assert await note_metadata_service.get_title_png_key(
            user_id=test_user_id, file_id=8403, bitmap_md5=DARK_GREY_TITLE_MD5
        ) == get_title_png_path(8403, DARK_GREY_TITLE_MD5)
        mock_render.assert_not_called()


async def test_get_title_png_key_returns_none_when_bitmap_left_note(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    """A persisted MD5 whose handwriting is no longer in the note file is not rendered."""
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8404
    )
    async with session_manager.session() as session:
        row = await session.get(NoteTitleDO, (test_user_id, 8404, 0))
        assert row is not None
        row.bitmap_md5 = "a" * 32
        await session.commit()

    assert (
        await note_metadata_service.get_title_png_key(
            user_id=test_user_id, file_id=8404, bitmap_md5="a" * 32
        )
        is None
    )


async def test_get_title_png_key_returns_none_for_unparseable_note(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8405
    )
    await file_service.blob_storage.put(
        USER_DATA_BUCKET, "headings_8405", b"not a note file"
    )

    assert (
        await note_metadata_service.get_title_png_key(
            user_id=test_user_id, file_id=8405, bitmap_md5=BLACK_TITLE_MD5
        )
        is None
    )


async def test_get_note_metadata_exposes_title_bitmap_md5(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8406
    )
    async with session_manager.session() as session:
        row = await session.get(NoteTitleDO, (test_user_id, 8406, 3))
        assert row is not None
        row.bitmap_md5 = None
        await session.commit()

    meta = await note_metadata_service.get_note_metadata(
        user_id=test_user_id, file_id=8406
    )

    assert meta is not None
    assert [(t.bitmap_md5, t.image_url) for t in meta.titles] == [
        (BLACK_TITLE_MD5, None),
        (DARK_GREY_TITLE_MD5, None),
        ("f14caee340e90ceab17cad156682ca9c", None),
        (None, None),
    ]


@pytest.mark.parametrize(
    ("user_offset", "bitmap_md5", "is_active"),
    [
        (1, BLACK_TITLE_MD5, "Y"),  # another user
        (0, "0" * 32, "Y"),  # MD5 of no persisted title
        (0, BLACK_TITLE_MD5, "N"),  # recycled note
    ],
    ids=["other_user", "unknown_md5", "inactive_file"],
)
async def test_get_title_png_key_returns_none_when_not_accessible(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
    user_offset: int,
    bitmap_md5: str,
    is_active: str,
) -> None:
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8402
    )
    async with session_manager.session() as session:
        file_do = await session.get(UserFileDO, 8402)
        assert file_do is not None
        file_do.is_active = is_active
        await session.commit()

    assert (
        await note_metadata_service.get_title_png_key(
            user_id=test_user_id + user_offset, file_id=8402, bitmap_md5=bitmap_md5
        )
        is None
    )


async def test_get_title_png_key_isolates_per_title_decode_failures(
    note_metadata_service: NoteMetadataService,
    session_manager: DatabaseSessionManager,
    file_service: FileService,
    test_user_id: int,
) -> None:
    """A decode failure on one title does not prevent other titles in the note from rendering."""
    await _hash_heading_note(
        session_manager, file_service, user_id=test_user_id, file_id=8407
    )
    real_convert_title = ImageConverter.convert_title
    call_count = 0

    def _flaky_convert_title(
        self: ImageConverter, title: fileformat.Title
    ) -> Image.Image:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise DecoderException("simulated corrupt title")
        return real_convert_title(self, title)

    with patch.object(ImageConverter, "convert_title", _flaky_convert_title):
        key = await note_metadata_service.get_title_png_key(
            user_id=test_user_id, file_id=8407, bitmap_md5=DARK_GREY_TITLE_MD5
        )

    assert key == get_title_png_path(8407, DARK_GREY_TITLE_MD5)
    png = await _read_cache(file_service, key)
    assert Image.open(io.BytesIO(png)).size == (582, 178)
