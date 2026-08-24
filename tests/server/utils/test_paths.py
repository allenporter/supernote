import uuid
from unittest.mock import patch

from supernote.server.utils.paths import (
    generate_inner_name,
    get_conversion_pdf_path,
    get_conversion_png_path,
    get_file_chunk_path,
    get_page_png_path,
    get_summary_group_id,
    get_summary_id,
    get_transcript_id,
)


def test_get_page_png_path() -> None:
    assert get_page_png_path(123, "page_1") == "123/pages/page_1.png"


def test_get_file_chunk_path() -> None:
    assert get_file_chunk_path("file_obj", 2) == "file_obj.part.2"


def test_get_summary_id() -> None:
    assert get_summary_id("file_key") == "file_key-summary"


def test_get_summary_group_id() -> None:
    assert get_summary_group_id("file_key") == "file_key-group"


def test_get_transcript_id() -> None:
    assert get_transcript_id("file_key") == "file_key-transcript"


def test_get_conversion_png_path() -> None:
    assert (
        get_conversion_png_path(1, 2, 3, "md5hash")
        == "conversions/1/2/page_3_md5hash.png"
    )


def test_get_conversion_pdf_path() -> None:
    assert (
        get_conversion_pdf_path(1, 2, "md5hash") == "conversions/1/2/note_md5hash.pdf"
    )


def test_generate_inner_name() -> None:
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("uuid.uuid4", return_value=fixed_uuid):
        assert (
            generate_inner_name("document.pdf", "DEVICE123")
            == "12345678-1234-5678-1234-567812345678-123.pdf"
        )
        assert (
            generate_inner_name("note.note", "12")
            == "12345678-1234-5678-1234-567812345678-12.note"
        )
        assert (
            generate_inner_name("note.note", None)
            == "12345678-1234-5678-1234-567812345678-000.note"
        )
