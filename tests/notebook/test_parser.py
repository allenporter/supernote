import io
from pathlib import Path

import pytest

from supernote.notebook import (
    SupernoteMetadata,
    exceptions,
    fileformat,
    load,
    load_notebook,
    parse_metadata,
)
from supernote.notebook.parser import SupernoteParser, SupernoteXParser
from supernote.notebook.schema import (
    EquipmentType,
    FileType,
    HeaderMetadata,
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
    assert meta.footer.keywords[0].keyword == ""

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


def test_parse_metadata_full_header(test_note_path: Path) -> None:
    with test_note_path.open("rb") as fd:
        notebook: SupernoteMetadata = parse_metadata(fd)
    assert notebook.header == HeaderMetadata(
        file_type=FileType.NOTE,
        apply_equipment=EquipmentType.N6,
        final_operation_page=1,
        final_operation_layer=1,
        device_dpi=0,
        soft_dpi=0,
        file_parse_type=0,
        ratta_etmd=0,
        file_id="F202512072214597017338I6OJBpDccy1",
        file_recogn_type=0,
        file_recogn_language=None,
        horizontal_check=0,
        is_old_apply_equipment=1,
        antialiasing_convert=2,
    )
    assert notebook.header.to_wire_dict() == {
        "FILE_TYPE": "NOTE",
        "APPLY_EQUIPMENT": "N6",
        "FINALOPERATION_PAGE": "1",
        "FINALOPERATION_LAYER": "1",
        "DEVICE_DPI": "0",
        "SOFT_DPI": "0",
        "FILE_PARSE_TYPE": "0",
        "RATTA_ETMD": "0",
        "FILE_ID": "F202512072214597017338I6OJBpDccy1",
        "FILE_RECOGN_TYPE": "0",
        "FILE_RECOGN_LANGUAGE": "none",
        "HORIZONTAL_CHECK": "0",
        "IS_OLD_APPLY_EQUIPMENT": "1",
        "ANTIALIASING_CONVERT": "2",
    }


def test_parse_metadata_rejects_negative_truncated_or_oversized_blocks() -> None:
    prefix = b"noteSN_FILE_VER_20230015"

    # Negative block address
    neg_footer = _pack_block(b"<FILE_FEATURE:-1><PAGE1:0>")
    neg_stream = io.BytesIO(
        prefix + neg_footer + len(prefix).to_bytes(fileformat.ADDRESS_SIZE, "little")
    )
    with pytest.raises(
        exceptions.ParserException, match="invalid negative block address"
    ):
        parse_metadata(neg_stream)

    # Truncated 4-byte block length header
    bad_footer_address = len(prefix) + 2
    trunc_stream = io.BytesIO(
        prefix + bad_footer_address.to_bytes(fileformat.ADDRESS_SIZE, "little")
    )
    with pytest.raises(
        exceptions.ParserException, match="unexpected EOF reading block length"
    ):
        parse_metadata(trunc_stream)

    # Block length exceeding remaining stream size
    oversized_length = (0xFFFFFFFF).to_bytes(fileformat.LENGTH_FIELD_SIZE, "little")
    oversized_stream = io.BytesIO(
        prefix
        + oversized_length
        + b"<PAGE1:0>"
        + len(prefix).to_bytes(fileformat.ADDRESS_SIZE, "little")
    )
    with pytest.raises(
        exceptions.ParserException, match="exceeds remaining stream size"
    ):
        load(oversized_stream)


def test_parser_file_parse_and_invalid_signature(
    test_note_path: Path, tmp_path: Path
) -> None:
    parser = SupernoteXParser()
    metadata = parser.parse(str(test_note_path), policy="strict")
    assert metadata.signature == "SN_FILE_VER_20230015"

    raw = bytearray(test_note_path.read_bytes())
    raw[4:24] = b"SN_FILE_VER_INVALID!"
    bad_note = tmp_path / "bad.note"
    bad_note.write_bytes(raw)

    with pytest.raises(exceptions.UnsupportedFileFormat, match="unknown signature"):
        parser.parse(str(bad_note), policy="strict")


def test_original_supernote_a5_parser_and_nonlayered_load() -> None:
    sig = b"SN_FILE_ASA_20190529"
    header_offset = len(sig)
    header_block = _pack_block(b"<FILE_TYPE:NOTE><APPLY_EQUIPMENT:A5>")

    data_offset = header_offset + len(header_block)
    data_block = _pack_block(b"RAW_PAGE_BITMAP")

    cover_offset = data_offset + len(data_block)
    cover_block = _pack_block(b"COVER_1_BYTES")

    page1_offset = cover_offset + len(cover_block)
    page1_block = _pack_block(
        f"<DATA:{data_offset}><PROTOCOL:SN_ASA_COMPRESS>".encode()
    )

    page2_offset = page1_offset + len(page1_block)
    page2_block = _pack_block(b"<DATA:0><PROTOCOL:SN_ASA_COMPRESS>")

    footer_offset = page2_offset + len(page2_block)
    footer_block = _pack_block(
        (
            f"<FILE_FEATURE:{header_offset}>"
            f"<COVER_1:{cover_offset}>"
            f"<PAGE:{page1_offset}>"
            f"<PAGE:{page2_offset}>"
            f"<EXTRA:v1><EXTRA:v2><EXTRA:v3>"
        ).encode()
    )
    tail = footer_offset.to_bytes(fileformat.ADDRESS_SIZE, "little")

    stream = io.BytesIO(
        sig
        + header_block
        + data_block
        + cover_block
        + page1_block
        + page2_block
        + footer_block
        + tail
    )

    notebook = load(stream)
    assert notebook.get_signature() == SupernoteParser.SN_SIGNATURES[0]
    assert notebook.get_total_pages() == 2
    assert notebook.get_cover().get_content() == b"COVER_1_BYTES"
    assert notebook.get_page(0).is_layer_supported() is False
    assert notebook.get_page(0).get_content() == b"RAW_PAGE_BITMAP"
    assert notebook.get_page(1).get_content() is None
    assert notebook.get_metadata().header.apply_equipment == EquipmentType.A5
    assert notebook.get_metadata().footer.extra["EXTRA"] == ["v1", "v2", "v3"]
