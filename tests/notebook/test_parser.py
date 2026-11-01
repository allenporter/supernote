import io
from pathlib import Path

import pytest

from supernote.notebook import (
    exceptions,
    fileformat,
    load,
    load_notebook,
    parse_metadata,
)


def _pack_block(payload: bytes) -> bytes:
    return len(payload).to_bytes(fileformat.LENGTH_FIELD_SIZE, "little") + payload


def _build_x_stream(
    *,
    header: bytes = b"<FILE_TYPE:NOTE>",
    footer_extra: bytes = b"",
    extra_blocks: list[bytes] | None = None,
    include_file_feature: bool = True,
) -> io.BytesIO:
    prefix = b"noteSN_FILE_VER_20230015"
    cursor = len(prefix)
    chunks = [prefix]

    header_addr = cursor
    header_block = _pack_block(header)
    chunks.append(header_block)
    cursor += len(header_block)

    for block in extra_blocks or []:
        chunks.append(block)
        cursor += len(block)

    footer_addr = cursor
    footer_payload = (
        f"<FILE_FEATURE:{header_addr}>".encode("ascii") if include_file_feature else b""
    ) + footer_extra
    footer_block = _pack_block(footer_payload)
    chunks.append(footer_block)
    chunks.append(b"tail")
    chunks.append(footer_addr.to_bytes(fileformat.ADDRESS_SIZE, "little"))
    return io.BytesIO(b"".join(chunks))


def test_load_notebook_valid_and_single_page(test_note_path: Path) -> None:
    notebook = load_notebook(test_note_path, page_number=0)
    assert notebook.get_total_pages() >= 1
    assert notebook.get_page(0) is not None


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"ab",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
    ],
)
def test_parse_metadata_rejects_short_or_binary_header_as_unsupported_format(
    payload: bytes,
) -> None:
    with pytest.raises(exceptions.UnsupportedFileFormat):
        parse_metadata(io.BytesIO(payload))


def test_parse_metadata_rejects_missing_or_invalid_file_feature() -> None:
    missing_stream = _build_x_stream(
        include_file_feature=False, footer_extra=b"<PAGE1:0>"
    )
    with pytest.raises(exceptions.ParserException, match="FILE_FEATURE"):
        parse_metadata(missing_stream)

    duplicate_stream = _build_x_stream(
        include_file_feature=True, footer_extra=b"<FILE_FEATURE:24>"
    )
    with pytest.raises(exceptions.ParserException, match="FILE_FEATURE"):
        parse_metadata(duplicate_stream)

    non_int_stream = _build_x_stream(
        include_file_feature=False, footer_extra=b"<FILE_FEATURE:corrupt>"
    )
    with pytest.raises(exceptions.ParserException, match="FILE_FEATURE"):
        parse_metadata(non_int_stream)


def test_parse_metadata_allows_zero_pages_and_rejects_invalid_page_addresses() -> None:
    zero_page_stream = _build_x_stream()
    metadata = parse_metadata(zero_page_stream)
    assert metadata.pages == []
    assert metadata.get_total_pages() == 0

    invalid_page_stream = _build_x_stream(footer_extra=b"<PAGE1:not_an_int>")
    with pytest.raises(exceptions.ParserException, match="PAGE1"):
        parse_metadata(invalid_page_stream)

    duplicate_page_stream = _build_x_stream(footer_extra=b"<PAGE1:0><PAGE1:0>")
    with pytest.raises(exceptions.ParserException, match="PAGE1"):
        parse_metadata(duplicate_page_stream)


def test_a5_parser_rejects_missing_or_invalid_page_address() -> None:
    prefix = b"SN_FILE_ASA_20190529"
    header_addr = len(prefix)
    header_block = _pack_block(b"<FILE_TYPE:NOTE>")
    footer_addr = header_addr + len(header_block)
    footer_block = _pack_block(f"<FILE_FEATURE:{header_addr}>".encode("ascii"))
    stream = io.BytesIO(
        prefix
        + header_block
        + footer_block
        + footer_addr.to_bytes(fileformat.ADDRESS_SIZE, "little")
    )
    with pytest.raises(exceptions.ParserException, match="PAGE"):
        parse_metadata(stream)


def test_parse_metadata_rejects_non_utf8_metadata_block() -> None:
    corrupt_header_stream = _build_x_stream(header=b"\xff\xfe\xfd")
    with pytest.raises(
        exceptions.ParserException, match="invalid UTF-8 metadata block"
    ):
        parse_metadata(corrupt_header_stream)


def test_parse_metadata_handles_empty_or_corrupt_keyword_blocks() -> None:
    prefix_len = len(b"noteSN_FILE_VER_20230015") + len(
        _pack_block(b"<FILE_TYPE:NOTE>")
    )
    kw_zero_block = _pack_block(b"<KEYWORDPAGE:1><KEYWORDSITE:0>")
    stream_zero = _build_x_stream(
        extra_blocks=[kw_zero_block],
        footer_extra=f"<KEYWORD_00010000:{prefix_len}>".encode("ascii"),
    )
    meta = parse_metadata(stream_zero)
    assert meta.footer[fileformat.KEY_KEYWORDS][0]["KEYWORD"] == ""

    bad_kw_content = _pack_block(b"\xff\xfe")
    kw_bad_utf8_addr = prefix_len + len(bad_kw_content)
    kw_bad_utf8_block = _pack_block(
        f"<KEYWORDPAGE:1><KEYWORDSITE:{prefix_len}>".encode("ascii")
    )
    stream_bad_utf8 = _build_x_stream(
        extra_blocks=[bad_kw_content, kw_bad_utf8_block],
        footer_extra=f"<KEYWORD_00010000:{kw_bad_utf8_addr}>".encode("ascii"),
    )
    with pytest.raises(
        exceptions.ParserException, match="invalid UTF-8 keyword content"
    ):
        parse_metadata(stream_bad_utf8)


def test_load_rejects_nonlayered_page_missing_data_offset() -> None:
    prefix = b"SN_FILE_ASA_20190529"
    header_addr = len(prefix)
    header_block = _pack_block(b"<FILE_TYPE:NOTE>")
    page_addr = header_addr + len(header_block)
    page_block = _pack_block(b"<PAGESTYLE:style_white>")
    footer_addr = page_addr + len(page_block)
    footer_block = _pack_block(
        f"<FILE_FEATURE:{header_addr}><PAGE:{page_addr}>".encode("ascii")
    )
    stream = io.BytesIO(
        prefix
        + header_block
        + page_block
        + footer_block
        + footer_addr.to_bytes(fileformat.ADDRESS_SIZE, "little")
    )
    with pytest.raises(exceptions.ParserException, match="DATA"):
        load(stream)
