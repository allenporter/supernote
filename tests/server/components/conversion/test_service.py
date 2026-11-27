"""Unit tests for ConversionService."""

import base64
import re
import zlib
from pathlib import Path

import pytest
from sqlalchemy import text

from supernote.models.summary import SummaryItem
from supernote.server.components.conversion import (
    CONVERSION_SERVICE_KEY,
    ConversionService,
    ConvertedBlob,
)
from supernote.server.components.conversion.service import _clean_markdown_for_pdf_text
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTitleDO,
    NoteTitleTranscriptDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import FileError, FileNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.utils.paths import get_conversion_pdf_path
from tests.server.components.conftest import LoadComponents


async def _read(blob_storage: BlobStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in blob_storage.get(CACHE_BUCKET, key)])


@pytest.fixture
async def conversion_service(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> ConversionService:
    await load_components("conversion", "web_ui", start=False)
    return component_core.app[CONVERSION_SERVICE_KEY]


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


async def test_convert_note_to_png_page_subset_only_renders_requested_page(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
) -> None:
    user_email = "test@example.com"
    file_id = 5005
    storage_key = "note_5005.note"
    multipage_note = Path("tests/testdata/mmujynya/stroller.note")

    await blob_storage.put(USER_DATA_BUCKET, storage_key, multipage_note.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="MultiPage.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_5005",
            )
        )
        await session.commit()

    cover_pages = await conversion_service.convert_note_to_png(
        user_email, file_id, page_indices={0}
    )
    assert cover_pages == [0]
    assert (
        await conversion_service.get_note_png_page(user_email, file_id, 0) is not None
    )
    assert await conversion_service.get_note_png_page(user_email, file_id, 1) is None

    all_pages = await conversion_service.convert_note_to_png(user_email, file_id)
    assert len(all_pages) >= 2
    assert (
        await conversion_service.get_note_png_page(user_email, file_id, 1) is not None
    )


async def test_convert_note_to_pdf_and_resolve(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5002
    storage_key = "note_5002.note"
    two_page_note = test_data_dir / "philips" / "blank-a6x-3.26.40-two-pages.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, two_page_note.read_bytes())
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
    selection_key = get_conversion_pdf_path(test_user_id, file_id, "md5_5002", [0])

    assert await conversion_service.get_note_pdf(user_email, file_id) == ConvertedBlob(
        storage_key=full_key,
        file_name="Project_Plan.pdf",
    )
    assert await _read(blob_storage, full_key) == full_pdf
    assert await conversion_service.get_note_pdf(
        user_email, file_id, [0]
    ) == ConvertedBlob(
        storage_key=selection_key,
        file_name="Project_Plan.pdf",
    )
    selection_pdf = await _read(blob_storage, selection_key)
    assert selection_pdf.startswith(b"%PDF")
    assert selection_pdf != full_pdf


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


DIGEST_MARK = "schaefer-dev/garmin_connect_20260016.pdf.mark"


async def test_convert_summary_to_pdf_and_png(
    conversion_service: ConversionService,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    user_email = "test@example.com"
    summary = SummaryItem(
        id=7001, handwrite_inner_name="digest.mark", handwrite_md5="hwmd5"
    )
    await blob_storage.put(
        USER_DATA_BUCKET, "digest.mark", (test_data_dir / DIGEST_MARK).read_bytes()
    )

    assert await conversion_service.get_summary_pdf(user_email, summary) is None
    assert await conversion_service.get_summary_png_page(user_email, summary, 0) is None

    await conversion_service.convert_summary_to_pdf(user_email, summary)
    pdf_blob = await conversion_service.get_summary_pdf(user_email, summary)
    assert pdf_blob == ConvertedBlob(
        storage_key=f"conversions/{test_user_id}/summary_7001/handwrite_hwmd5.pdf",
        file_name="summary_7001.pdf",
    )
    assert (await _read(blob_storage, pdf_blob.storage_key)).startswith(b"%PDF")

    assert await conversion_service.convert_summary_to_png(user_email, summary) == [0]
    png_blob = await conversion_service.get_summary_png_page(user_email, summary, 0)
    assert png_blob is not None
    assert (await _read(blob_storage, png_blob.storage_key)).startswith(b"\x89PNG")
    assert await conversion_service.get_summary_png_page(user_email, summary, 1) is None

    # Cached renders are served without reading the source `.mark` blob again.
    await blob_storage.delete(USER_DATA_BUCKET, "digest.mark")
    await conversion_service.convert_summary_to_pdf(user_email, summary)
    assert await conversion_service.convert_summary_to_png(user_email, summary) == [0]


async def test_convert_summary_validation_errors(
    conversion_service: ConversionService,
    test_user_id: int,
) -> None:
    user_email = "test@example.com"
    no_handwriting = SummaryItem(id=7002)
    no_md5 = SummaryItem(id=7003, handwrite_inner_name="digest.mark")
    unsafe_md5 = SummaryItem(
        id=7004, handwrite_inner_name="digest.mark", handwrite_md5="../escape"
    )
    missing_blob = SummaryItem(
        id=7005, handwrite_inner_name="missing.mark", handwrite_md5="hwmd5"
    )

    for convert in (
        conversion_service.convert_summary_to_pdf,
        conversion_service.convert_summary_to_png,
    ):
        with pytest.raises(FileNotFound, match="Handwriting data not found"):
            await convert(user_email, no_handwriting)
        with pytest.raises(FileError, match="missing handwriting MD5"):
            await convert(user_email, no_md5)
        with pytest.raises(FileError, match="Invalid handwrite_md5"):
            await convert(user_email, unsafe_md5)
        with pytest.raises(FileNotFound, match="Handwriting data not found"):
            await convert(user_email, missing_blob)

    with pytest.raises(FileError, match="missing handwriting MD5"):
        await conversion_service.get_summary_pdf(user_email, no_md5)
    with pytest.raises(FileError, match="Invalid handwrite_md5"):
        await conversion_service.get_summary_png_page(user_email, unsafe_md5, 0)


_PDF_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.DOTALL)


def _extract_decompressed_pdf_streams(pdf_bytes: bytes) -> bytes:
    """Return joined decompressed PDF content streams for text assertions."""
    streams: list[bytes] = []
    for match in _PDF_STREAM_RE.finditer(pdf_bytes):
        data = match.group(1).strip()
        if data.endswith(b"~>"):
            data = base64.a85decode(data[:-2])
        try:
            streams.append(zlib.decompress(data))
        except zlib.error:
            streams.append(data)
    return b"\n".join(streams)


def test_clean_markdown_for_pdf_text_strips_markdown_and_mermaid_boilerplate() -> None:
    raw = """\
## Sprint Planning
- [x] Ship **searchable** `PDF` export
> See [design doc](https://example.com/spec)

| Owner | Status |
| :--- | :---: |
| Alice | Done |

---

```mermaid
flowchart TD
    subgraph Backend
        A["Auth Service"] --> B["SQLite Store"]
    end
    classDef muted fill:#eee
```
"""
    cleaned = _clean_markdown_for_pdf_text(raw)

    assert cleaned == "\n".join(
        [
            "Sprint Planning",
            "Ship searchable PDF export",
            "See design doc",
            "Owner Status",
            "Alice Done",
            "Backend",
            "A Auth Service B SQLite Store",
        ]
    )


async def test_convert_note_to_pdf_embeds_ocr_text_and_toc_outlines(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5010
    storage_key = "note_5010.note"
    two_page_note = test_data_dir / "philips" / "blank-a6x-3.26.40-two-pages.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, two_page_note.read_bytes())
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Architecture.note",
                    is_folder="N",
                    storage_key=storage_key,
                    md5="md5_5010",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="P0",
                    text_content=(
                        "# Overview\n```mermaid\nflowchart TD\n"
                        'A["Gateway"] --> B["Worker"]\n```\n'
                    ),
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="P1",
                    text_content="Follow up action items",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=0,
                    page_index=0,
                    level=1,
                    bitmap_md5="md5_title_0",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=1,
                    page_index=0,
                    level=2,
                    bitmap_md5="md5_untranscribed",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=2,
                    page_index=1,
                    level=2,
                    bitmap_md5="md5_title_1",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=3,
                    page_index=1,
                    level=2,
                    bitmap_md5="md5_blank",
                ),
                # Another user's title on the same file_id must not leak into this PDF.
                NoteTitleDO(
                    user_id=test_user_id + 999,
                    file_id=file_id,
                    title_index=0,
                    page_index=0,
                    level=1,
                    bitmap_md5="md5_other_user",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    bitmap_md5="md5_title_0",
                    text_content="System Architecture",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    bitmap_md5="md5_title_1",
                    text_content="Next Steps",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    bitmap_md5="md5_blank",
                    text_content="   ",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id + 999,
                    file_id=file_id,
                    bitmap_md5="md5_other_user",
                    text_content="Foreign Tenant Heading",
                ),
            ]
        )
        await session.commit()

    await conversion_service.convert_note_to_pdf(user_email, file_id, page_no_list=[])
    full_key = get_conversion_pdf_path(test_user_id, file_id, "md5_5010")
    pdf_bytes = await _read(blob_storage, full_key)

    streams = _extract_decompressed_pdf_streams(pdf_bytes)
    assert b"3 Tr" in streams
    assert b"Overview" in streams
    assert b"Gateway" in streams
    assert b"Worker" in streams
    assert b"Follow up action items" in streams
    assert b"flowchart" not in streams
    assert b"mermaid" not in streams

    assert b"/Outlines" in pdf_bytes
    assert b"(System Architecture)" in pdf_bytes
    assert b"(Next Steps)" in pdf_bytes
    assert b"(Foreign Tenant Heading)" not in pdf_bytes


async def test_convert_note_to_pdf_partial_pages_filters_toc_and_text(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5011
    storage_key = "note_5011.note"
    two_page_note = test_data_dir / "philips" / "blank-a6x-3.26.40-two-pages.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, two_page_note.read_bytes())
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Partial.note",
                    is_folder="N",
                    storage_key=storage_key,
                    md5="md5_5011",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="P0",
                    text_content="Excluded page zero text",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="P1",
                    text_content="Included page one text",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=0,
                    page_index=0,
                    level=1,
                    bitmap_md5="md5_p0",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    title_index=1,
                    page_index=1,
                    level=1,
                    bitmap_md5="md5_p1",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    bitmap_md5="md5_p0",
                    text_content="Page Zero Heading",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    bitmap_md5="md5_p1",
                    text_content="Page One Heading",
                ),
            ]
        )
        await session.commit()

    await conversion_service.convert_note_to_pdf(user_email, file_id, page_no_list=[1])
    selection_key = get_conversion_pdf_path(test_user_id, file_id, "md5_5011", [1])
    pdf_bytes = await _read(blob_storage, selection_key)

    streams = _extract_decompressed_pdf_streams(pdf_bytes)
    assert b"Included page one text" in streams
    assert b"Excluded page zero text" not in streams
    assert b"(Page One Heading)" in pdf_bytes
    assert b"(Page Zero Heading)" not in pdf_bytes


async def test_convert_note_to_pdf_handles_missing_title_transcript_table(
    conversion_service: ConversionService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    user_email = "test@example.com"
    file_id = 5012
    storage_key = "note_5012.note"

    await blob_storage.put(USER_DATA_BUCKET, storage_key, test_note_path.read_bytes())
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Legacy.note",
                    is_folder="N",
                    storage_key=storage_key,
                    md5="md5_5012",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="P0",
                    text_content="Legacy OCR transcript",
                ),
            ]
        )
        await session.execute(
            text(
                "ALTER TABLE f_note_title_transcript RENAME TO f_note_title_transcript_bak"
            )
        )
        await session.commit()

    try:
        await conversion_service.convert_note_to_pdf(
            user_email, file_id, page_no_list=[]
        )
        full_key = get_conversion_pdf_path(test_user_id, file_id, "md5_5012")
        pdf_bytes = await _read(blob_storage, full_key)

        streams = _extract_decompressed_pdf_streams(pdf_bytes)
        assert b"Legacy OCR transcript" in streams
        assert b"/Outlines" not in pdf_bytes
    finally:
        async with session_manager.session() as session:
            await session.execute(
                text(
                    "ALTER TABLE f_note_title_transcript_bak RENAME TO f_note_title_transcript"
                )
            )
            await session.commit()
