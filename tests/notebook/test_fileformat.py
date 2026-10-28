import json
from collections.abc import Callable

import pytest

from supernote.notebook import fileformat


def test_supernote_metadata_properties_and_to_json() -> None:
    meta = fileformat.SupernoteMetadata(
        type="note",
        signature="SN_FILE_VER_20230015",
        header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        footer={"FILE_FEATURE": "24"},
        pages=[{"PAGEID": "P1"}],
    )

    assert meta.get_total_pages() == 1
    assert meta.is_layer_supported(0) is False

    with pytest.raises(IndexError, match="page number out of range"):
        meta.is_layer_supported(1)

    parsed_json = json.loads(meta.to_json(indent=2))
    assert parsed_json == {
        "__type__": "note",
        "__signature__": "SN_FILE_VER_20230015",
        "__header__": {"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        "__footer__": {"FILE_FEATURE": "24"},
        "__pages__": [{"PAGEID": "P1"}],
    }

    # Verify property setters update the underlying structure
    meta.type = "mark"
    meta.signature = "SN_FILE_VER_20260016"
    meta.header = {"FILE_TYPE": "MARK"}
    meta.footer = {"FILE_FEATURE": "32"}
    meta.pages = [{"PAGEID": "P2"}]
    assert (meta.type, meta.signature, meta.header, meta.footer, meta.pages) == (
        "mark",
        "SN_FILE_VER_20260016",
        {"FILE_TYPE": "MARK"},
        {"FILE_FEATURE": "32"},
        [{"PAGEID": "P2"}],
    )


def test_notebook_dimensions_and_page_access(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    n5_notebook = make_notebook(header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N5"})
    assert (n5_notebook.get_width(), n5_notebook.get_height()) == (
        fileformat.A5X2_PAGE_WIDTH,
        fileformat.A5X2_PAGE_HEIGHT,
    )

    with pytest.raises(IndexError, match="page number out of range"):
        n5_notebook.get_page(5)


def test_page_and_layer_accessors() -> None:
    non_layered = fileformat.Page(
        {
            "PAGEID": "P0",
            "PROTOCOL": "SN_ASA_COMPRESS",
            "PAGESTYLE": "style_white",
            "PAGESTYLEMD5": "0",
            "LAYERINFO": "none",
            "RECOGNSTATUS": "0",
        }
    )
    assert non_layered.is_layer_supported() is False
    assert non_layered.get_protocol() == "SN_ASA_COMPRESS"
    assert non_layered.get_style() == "style_white"
    assert non_layered.get_style_hash() == ""
    assert non_layered.get_layer_info() is None
    assert non_layered.get_layer_order() == []
    assert non_layered.get_orientation() == fileformat.Page.ORIENTATION_VERTICAL
    assert non_layered.is_horizontal() is False

    non_layered.set_recogn_file(b"recogn-file-bytes")
    assert non_layered.get_recogn_file() == b"recogn-file-bytes"

    layered = fileformat.Page(
        {
            "PAGEID": "P1",
            "PAGESTYLEMD5": "abc123",
            "LAYERINFO": '[{"layerId"#0}]',
            "LAYERSEQ": "MAINLAYER,BGLAYER",
            "ORIENTATION": fileformat.Page.ORIENTATION_HORIZONTAL,
            fileformat.KEY_LAYERS: [
                {
                    "LAYERNAME": "MAINLAYER",
                    "LAYERPROTOCOL": "RATTA_RLE",
                    "LAYERTYPE": "MARK",
                }
                for _ in range(5)
            ],
        }
    )
    assert layered.is_layer_supported() is True
    assert layered.get_protocol() == "RATTA_RLE"
    assert layered.get_style_hash() == "abc123"
    assert layered.get_layer_info() == '[{"layerId":0}]'
    assert layered.get_layer_order() == ["MAINLAYER", "BGLAYER"]
    assert layered.is_horizontal() is True

    layer0 = layered.get_layer(0)
    assert layer0.get_name() == "MAINLAYER"
    assert layer0.get_protocol() == "RATTA_RLE"
    assert layer0.get_type() == "MARK"

    with pytest.raises(IndexError, match="layer number out of range"):
        layered.get_layer(5)


def test_keyword_title_link_accessors() -> None:
    kw = fileformat.Keyword(
        {
            "KEYWORDPAGE": "2",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "hello",
        }
    )
    assert kw.get_page_number() == 1
    assert kw.get_position_string() == "0020"
    assert kw.get_keyword() == "hello"
    assert kw.get_rect() == (10, 20, 40, 60)

    link = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "5,15,25,35",
            "LINKTIMESTAMP": "987654321",
            "LINKFILE": "encoded_path",
            "LINKFILEID": "F123",
            "PAGEID": "P456",
        }
    )
    assert link.get_type() == fileformat.Link.TYPE_PAGE_LINK
    assert link.get_inout() == fileformat.Link.DIRECTION_OUT
    assert link.get_position_string() == "0015000500350025"
    assert link.get_rect() == (5, 15, 30, 50)
    assert link.get_timestamp() == "987654321"
    assert link.get_filepath() == "encoded_path"
    assert link.get_fileid() == "F123"
    assert link.get_pageid() == "P456"
