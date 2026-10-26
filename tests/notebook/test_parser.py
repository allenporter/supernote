import io
from pathlib import Path

import pytest

from supernote.notebook import (
    SupernoteMetadata,
    exceptions,
    fileformat,
    load,
    parse_metadata,
)
from supernote.notebook.parser import SupernoteParser, SupernoteXParser


def _pack_block(payload: bytes) -> bytes:
    return len(payload).to_bytes(fileformat.LENGTH_FIELD_SIZE, "little") + payload


def test_parse_metadata(test_note_path: Path) -> None:
    with test_note_path.open("rb") as fd:
        notebook: SupernoteMetadata = parse_metadata(fd)
    assert notebook.header == {
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


def test_parse_metadata_rejects_negative_block_address() -> None:
    prefix = b"noteSN_FILE_VER_20230015"
    footer_block = _pack_block(b"<FILE_FEATURE:-1><PAGE:0>")
    tail = len(prefix).to_bytes(fileformat.ADDRESS_SIZE, "little")
    stream = io.BytesIO(prefix + footer_block + tail)

    with pytest.raises(
        exceptions.ParserException, match="invalid negative block address"
    ):
        parse_metadata(stream)


def test_parse_metadata_rejects_truncated_block_length_header() -> None:
    prefix = b"noteSN_FILE_VER_20230015"
    bad_footer_address = len(prefix) + 2
    tail = bad_footer_address.to_bytes(fileformat.ADDRESS_SIZE, "little")
    stream = io.BytesIO(prefix + tail)

    with pytest.raises(
        exceptions.ParserException, match="unexpected EOF reading block length"
    ):
        parse_metadata(stream)


def test_load_rejects_block_length_exceeding_stream_size() -> None:
    prefix = b"noteSN_FILE_VER_20230015"
    oversized_length = (0xFFFFFFFF).to_bytes(fileformat.LENGTH_FIELD_SIZE, "little")
    tail = len(prefix).to_bytes(fileformat.ADDRESS_SIZE, "little")
    stream = io.BytesIO(prefix + oversized_length + b"<PAGE:0>" + tail)

    with pytest.raises(
        exceptions.ParserException, match="exceeds remaining stream size"
    ):
        load(stream)


def test_parse_metadata_rejects_unsupported_file_format() -> None:
    stream = io.BytesIO(b"not-a-supernote-file-header-at-all")
    with pytest.raises(
        exceptions.UnsupportedFileFormat, match="unsupported file format"
    ):
        parse_metadata(stream)


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
    # Build a minimal valid original A5 (SN_FILE_ASA_20190529) stream with non-layered pages
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
    # Include duplicate keys to exercise list aggregation in _extract_parameters and _get_page_addresses
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
    footer = notebook.get_metadata().footer
    assert footer is not None
    assert footer["EXTRA"] == ["v1", "v2", "v3"]
