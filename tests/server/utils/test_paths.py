import uuid
from unittest.mock import patch

import pytest

from supernote.server.utils.paths import (
    AI_SUMMARIES_GROUP_NAME,
    flatten_vfs_path,
    generate_inner_name,
    get_ai_summaries_group_id,
    get_conversion_pdf_path,
    get_conversion_pdf_prefix,
    get_file_chunk_path,
    get_full_conversion_pdf_path,
    get_page_png_path,
    get_summary_id,
    is_valid_page_id,
    parse_file_chunk_name,
)


def test_flatten_vfs_path() -> None:
    assert flatten_vfs_path("/NOTE/Note/Work/daily.note") == "Note/Work/daily.note"
    assert (
        flatten_vfs_path("DOCUMENT/Document/Archive/paper.pdf")
        == "Document/Archive/paper.pdf"
    )
    assert flatten_vfs_path("/EXPORT/summary.pdf") == "Export/summary.pdf"
    assert flatten_vfs_path("Note/daily.note") == "Note/daily.note"
    assert flatten_vfs_path("") == ""


def test_get_page_png_path() -> None:
    assert get_page_png_path(123, "page_1") == "123/pages/page_1.png"
    assert is_valid_page_id("P20260101120000")
    assert not is_valid_page_id("../../102/pages/victim")
    with pytest.raises(ValueError, match="Invalid page_id"):
        get_page_png_path(123, "../../102/pages/victim")


def test_get_file_chunk_path() -> None:
    assert get_file_chunk_path("file_obj", 2) == "file_obj.part.2"


def test_parse_file_chunk_name() -> None:
    assert parse_file_chunk_name("file_obj.part.2") == "file_obj"
    assert (
        parse_file_chunk_name("user_data/uuid-123.pdf.part.10")
        == "user_data/uuid-123.pdf"
    )
    assert parse_file_chunk_name("regular_file.txt") is None
    assert parse_file_chunk_name("invalid.part.notanumber") is None
    assert parse_file_chunk_name(".part.1") is None


def test_get_summary_id() -> None:
    sid = get_summary_id(1, 42)
    assert len(sid) == 32
    assert sid == sid.lower()
    int(sid, 16)
    assert sid == get_summary_id(1, 42)
    assert sid != get_summary_id(1, 43)
    assert sid != get_summary_id(2, 42)


def test_get_ai_summaries_group_id() -> None:
    assert AI_SUMMARIES_GROUP_NAME == "AI Summaries"
    gid = get_ai_summaries_group_id(1)
    assert len(gid) == 32
    assert gid == gid.lower()
    int(gid, 16)
    assert gid == get_ai_summaries_group_id(1)
    assert gid != get_ai_summaries_group_id(2)
    assert gid != get_summary_id(1, 42)


def test_get_conversion_pdf_path() -> None:
    assert (
        get_conversion_pdf_path(1, 2, "md5hash") == "conversions/1/2/note_md5hash.pdf"
    )
    assert get_conversion_pdf_path(1, 2, "md5hash", []) == (
        "conversions/1/2/note_md5hash.pdf"
    )

    selection = get_conversion_pdf_path(1, 2, "md5hash", [0, 2])
    assert selection.startswith("conversions/1/2/note_md5hash_pages_")
    assert selection != get_conversion_pdf_path(1, 2, "md5hash", [2, 0])
    assert selection.startswith(get_conversion_pdf_prefix(1, 2, "md5hash"))

    with pytest.raises(ValueError, match="file_md5"):
        get_conversion_pdf_prefix(1, 2, "")


def test_get_full_conversion_pdf_path() -> None:
    full = get_conversion_pdf_path(1, 2, "md5hash")
    selection = get_conversion_pdf_path(1, 2, "md5hash", [3])
    assert get_full_conversion_pdf_path(selection) == full
    assert get_full_conversion_pdf_path(full) is None
    assert get_full_conversion_pdf_path("2/pages/P1.png") is None


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
