import json
import zlib
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from supernote.notebook import (
    Keyword,
    Notebook,
    Page,
    SupernoteMetadata,
    decoder,
    exceptions,
    fileformat,
    load,
)


def _make_metadata(**overrides: Any) -> SupernoteMetadata:
    kwargs: dict[str, Any] = {
        "type": "note",
        "signature": "SN_FILE_VER_20230015",
        "header": {"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        "footer": {},
        "pages": [],
    }
    kwargs.update(overrides)
    return SupernoteMetadata(**kwargs)


def test_supernote_metadata_construction_and_wire_json_serialization() -> None:
    metadata = _make_metadata(pages=[{"PAGEID": "P1", "__layers__": []}])
    assert metadata.type == "note"
    assert metadata.signature == "SN_FILE_VER_20230015"
    assert metadata.get_total_pages() == 1
    assert metadata.is_layer_supported(0) is True

    serialized = json.loads(metadata.to_json(indent=2))
    assert serialized == {
        "__type__": "note",
        "__signature__": "SN_FILE_VER_20230015",
        "__header__": {"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        "__footer__": {},
        "__pages__": [{"PAGEID": "P1", "__layers__": []}],
    }


def test_supernote_metadata_is_layer_supported_rejects_out_of_range_page() -> None:
    metadata = _make_metadata(pages=[{"PAGEID": "P1", "__layers__": []}])
    with pytest.raises(IndexError, match="page number out of range"):
        metadata.is_layer_supported(1)


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("type", "notebook metadata type is missing"),
        ("signature", "notebook metadata signature is missing"),
        ("header", "notebook metadata header is missing"),
        ("footer", "notebook metadata footer is missing"),
        ("pages", "notebook metadata pages are missing"),
    ],
)
def test_supernote_metadata_rejects_missing_fields_on_init_and_mutation(
    field: str, match: str
) -> None:
    with pytest.raises(exceptions.ParserException, match=match):
        _make_metadata(**{field: cast(Any, None)})

    metadata = _make_metadata()
    with pytest.raises(exceptions.ParserException, match=match):
        setattr(metadata, field, cast(Any, None))


def test_supernote_metadata_rejects_invalid_page_entry() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid page metadata entry"):
        _make_metadata(pages=[cast(Any, None)])


def test_notebook_rejects_missing_metadata() -> None:
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        Notebook(cast(Any, None))

    notebook = Notebook(_make_metadata())
    object.__setattr__(notebook, "metadata", None)
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        notebook.get_metadata()


def test_notebook_basic_accessors_and_highres_grayscale_support() -> None:
    notebook = Notebook(_make_metadata())
    assert notebook.get_type() == "note"
    assert notebook.get_signature() == "SN_FILE_VER_20230015"
    assert notebook.get_total_pages() == 0
    assert notebook.supports_highres_grayscale() is True

    short_sig_notebook = Notebook(_make_metadata(signature="SHORT"))
    assert short_sig_notebook.supports_highres_grayscale() is False


def test_notebook_n5_dimensions_and_page_bounds() -> None:
    n5_notebook = Notebook(
        _make_metadata(header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N5"})
    )
    assert (n5_notebook.get_width(), n5_notebook.get_height()) == (
        fileformat.A5X2_PAGE_WIDTH,
        fileformat.A5X2_PAGE_HEIGHT,
    )

    with pytest.raises(IndexError, match="page number out of range"):
        n5_notebook.get_page(0)


@pytest.mark.parametrize(
    ("raw_kw", "match"),
    [
        (None, "invalid keyword metadata"),
        ({}, "KEYWORDPAGE"),
        ({"KEYWORDPAGE": "not-an-int"}, "KEYWORDPAGE"),
    ],
)
def test_keyword_rejects_invalid_or_missing_page_metadata(
    raw_kw: Any, match: str
) -> None:
    with pytest.raises(exceptions.ParserException, match=match):
        Keyword(raw_kw)


def test_page_rejects_invalid_page_or_layer_metadata() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid page metadata"):
        Page(cast(Any, None))

    with pytest.raises(exceptions.ParserException, match="invalid layer metadata"):
        Page({fileformat.KEY_LAYERS: [cast(Any, None)]})


def test_page_empty_layers_list_and_layer_bounds() -> None:
    empty_layered_page = Page({fileformat.KEY_LAYERS: []})
    assert empty_layered_page.is_layer_supported() is True
    assert empty_layered_page.get_layers() == []
    assert empty_layered_page.get_protocol() is None
    with pytest.raises(IndexError, match="layer number out of range"):
        empty_layered_page.get_layer(0)


def test_page_style_and_hash_accessors() -> None:
    page = Page({"PAGESTYLE": "user_custom"})
    assert page.get_style() == "user_custom"
    assert page.get_style_hash() == ""
    assert page.get_layer_info() is None
    assert page.get_layer_order() == []
    assert page.get_recogn_status() == Page.RECOGNSTATUS_NONE

    page.metadata.style_md5 = None
    assert page.get_style_hash() == ""
    page.metadata.style_md5 = "abc123"
    assert page.get_style_hash() == "abc123"


def test_page_rejects_non_integer_recogn_status() -> None:
    with pytest.raises(exceptions.ParserException, match="RECOGNSTATUS"):
        Page({"RECOGNSTATUS": "bad"})


def test_cover_constructor_initialization() -> None:
    cover = fileformat.Cover(content=b"cover-bytes")
    assert cover.get_content() == b"cover-bytes"


def test_keyword_constructor_initialization() -> None:
    kw = Keyword(
        {
            "KEYWORDPAGE": "2",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "hello",
        },
        content=b"kw-bytes",
    )
    assert kw.get_content() == b"kw-bytes"
    assert kw.get_page_number() == 1
    assert kw.get_position_string() == "0020"
    assert kw.get_keyword() == "hello"
    assert kw.get_rect() == (10, 20, 40, 60)


def test_title_constructor_initialization() -> None:
    title = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLE": "Heading"},
        content=b"title-bytes",
        page_number=3,
    )
    assert title.get_content() == b"title-bytes"
    assert title.get_page_number() == 3
    assert title.get_position_string() == "00200010"


def test_link_constructor_initialization() -> None:
    link = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "5,15,25,35",
            "LINKTIMESTAMP": "987654321",
            "LINKFILE": "encoded_path",
            "LINKFILEID": "F123",
            "PAGEID": "P456",
        },
        content=b"link-bytes",
        page_number=2,
    )
    assert link.get_content() == b"link-bytes"
    assert link.get_page_number() == 2
    assert link.get_type() == fileformat.Link.TYPE_PAGE_LINK
    assert link.get_inout() == fileformat.Link.DIRECTION_OUT
    assert link.get_position_string() == "0015000500350025"
    assert link.get_rect() == (5, 15, 30, 50)
    assert link.get_timestamp() == "987654321"
    assert link.get_filepath() == "encoded_path"
    assert link.get_fileid() == "F123"
    assert link.get_pageid() == "P456"


def test_layer_constructor_initialization() -> None:
    layer = fileformat.Layer(
        {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE", "LAYERTYPE": "MARK"},
        content=b"layer-bytes",
    )
    assert layer.get_content() == b"layer-bytes"
    assert layer.get_name() == "MAINLAYER"
    assert layer.get_protocol() == "RATTA_RLE"
    assert layer.get_type() == "MARK"


def test_page_has_ink_and_style(test_note_path: Path, test_data_dir: Path) -> None:
    # 20251207_221454.note is a 1-page blank dot-grid notebook
    with test_note_path.open("rb") as fd:
        blank_nb = load(fd)
    blank_page = blank_nb.get_page(0)
    assert blank_page.get_style() == "style_5mm_dots"
    assert blank_page.has_ink() is False

    # sn2md_20260618.note has visible handwriting on a four_quadrant_method template
    written_path = test_data_dir / "dsummersl" / "sn2md_20260618.note"
    with written_path.open("rb") as fd:
        written_nb = load(fd, policy="loose")
    written_page = written_nb.get_page(0)
    assert written_page.get_style() == "style_four_quadrant_method"
    assert written_page.has_ink() is True

    # Hidden layer with strokes should not count as visible ink
    hidden_layer_page = fileformat.Page(
        {
            "PAGEID": "P20250101000000abc",
            "PAGESTYLE": "style_white",
            "LAYERSEQ": "LAYER1,MAINLAYER,BGLAYER",
            "LAYERINFO": '[{"layerId":0,"isBackgroundLayer":false,"isVisible":true},'
            '{"layerId":1,"isBackgroundLayer":false,"isVisible":false},'
            '{"layerId":3,"isBackgroundLayer":true,"isVisible":true}]',
            fileformat.KEY_LAYERS: [
                {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
                {"LAYERNAME": "LAYER1", "LAYERPROTOCOL": "RATTA_RLE"},
                {"LAYERNAME": "LAYER2", "LAYERPROTOCOL": "RATTA_RLE"},
                {"LAYERNAME": "LAYER3", "LAYERPROTOCOL": "RATTA_RLE"},
                {"LAYERNAME": "BGLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
            ],
        }
    )
    hidden_layer_page.get_layer(0).set_content(
        bytes([decoder.RattaRleDecoder.COLORCODE_BACKGROUND, 0xFF])
    )
    hidden_layer_page.get_layer(1).set_content(
        bytes([decoder.RattaRleDecoder.COLORCODE_BLACK, 0x05])
    )
    assert hidden_layer_page.has_ink() is False

    # Textbox content marks page as non-blank even with transparent RLE
    textbox_page = fileformat.Page(
        {
            "PAGEID": "P20250101000001abc",
            "PAGESTYLE": "style_white",
            "PAGETEXTBOX": "1234",
            "PROTOCOL": "RATTA_RLE",
        }
    )
    textbox_page.set_content(
        bytes([decoder.RattaRleDecoder.COLORCODE_BACKGROUND, 0xFF])
    )
    assert textbox_page.has_ink() is True


def test_page_has_ink_flate_and_non_layered_edge_cases() -> None:
    # Duplicate MAINLAYER remapping + missing layer name + SN_ASA_COMPRESS full buffer
    blank_flate_buf = np.full(
        (
            decoder.FlateDecoder.INTERNAL_PAGE_WIDTH,
            decoder.FlateDecoder.INTERNAL_PAGE_HEIGHT,
        ),
        decoder.FlateDecoder.COLORCODE_BACKGROUND,
        dtype=np.uint16,
    )
    # Put non-background values in the 16-column right margin that FlateDecoder strips
    blank_flate_buf[:, -16:] = 0x0000
    compressed_blank = zlib.compress(blank_flate_buf.tobytes())

    flate_page = fileformat.Page(
        {
            "PAGEID": "P20250101000002abc",
            "LAYERINFO": "none",
            fileformat.KEY_LAYERS: [
                {
                    "LAYERNAME": "MAINLAYER",
                    "LAYERPROTOCOL": "SN_ASA_COMPRESS",
                    "LAYERTYPE": "MARK",
                },
                {
                    "LAYERNAME": "MAINLAYER",
                    "LAYERPROTOCOL": "SN_ASA_COMPRESS",
                    "LAYERTYPE": "BACKGROUND",
                },
                {"LAYERPROTOCOL": "RATTA_RLE"},
            ],
        }
    )
    flate_page.get_layer(0).set_content(compressed_blank)
    flate_page.get_layer(1).set_content(bytes([0x00, 0x05]))
    assert flate_page.has_ink() is False

    # Corrupt SN_ASA_COMPRESS raises DecoderException
    corrupt_flate = fileformat.Page({"PROTOCOL": "SN_ASA_COMPRESS"})
    corrupt_flate.set_content(b"not-zlib")
    with pytest.raises(
        exceptions.DecoderException, match="failed to decompress bitmap"
    ):
        corrupt_flate.has_ink()

    # Unknown protocol with non-empty data conservatively returns True; empty returns False
    unknown_page = fileformat.Page({"PROTOCOL": "FUTURE_CODEC"})
    assert unknown_page.has_ink() is False
    unknown_page.set_content(b"\x01\x02")
    assert unknown_page.has_ink() is True
