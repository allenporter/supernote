import json
from typing import Any, cast

import pytest

from supernote.notebook import (
    Cover,
    Keyword,
    Layer,
    Link,
    Notebook,
    Page,
    SupernoteMetadata,
    Title,
    exceptions,
    fileformat,
)
from supernote.notebook.schema import (
    LayerName,
    LayerProtocol,
    LayerType,
    LinkDirection,
    LinkType,
    PageOrientation,
    RecognitionStatus,
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


# --- SupernoteMetadata Tests ---


def test_supernote_metadata_construction_and_wire_json_serialization() -> None:
    metadata = _make_metadata(pages=[{"PAGEID": "P1", "__layers__": []}])
    assert metadata.type == "note"
    assert metadata.signature == "SN_FILE_VER_20230015"
    assert metadata.total_pages == 1
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


# --- Notebook Domain Property Tests ---


def test_notebook_rejects_missing_metadata() -> None:
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        Notebook(cast(Any, None))

    notebook = Notebook(_make_metadata())
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        notebook.metadata = cast(Any, None)

    object.__setattr__(notebook, "_metadata", None)
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        _ = notebook.metadata


def test_notebook_properties_and_setters() -> None:
    notebook = Notebook(
        _make_metadata(
            header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6", "FILE_ID": "FID1"}
        )
    )
    assert notebook.type == "note"
    assert notebook.signature == "SN_FILE_VER_20230015"
    assert notebook.total_pages == 0
    assert notebook.file_id == "FID1"
    assert (notebook.width, notebook.height) == (
        fileformat.PAGE_WIDTH,
        fileformat.PAGE_HEIGHT,
    )

    notebook.type = "mark"
    notebook.signature = "SN_FILE_VER_20210010"
    notebook.width = 800
    notebook.height = 600
    assert notebook.metadata.type == "mark"
    assert notebook.metadata.signature == "SN_FILE_VER_20210010"
    assert (notebook.page_width, notebook.page_height) == (800, 600)


def test_notebook_highres_grayscale_and_realtime_predicates() -> None:
    notebook = Notebook(
        _make_metadata(
            header={"FILE_TYPE": "NOTE", "FILE_RECOGN_TYPE": "1"},
            signature="SN_FILE_VER_20230015",
        )
    )
    assert notebook.supports_highres_grayscale() is True
    assert notebook.is_realtime_recognition() is True

    short_sig_notebook = Notebook(_make_metadata(signature="SHORT"))
    assert short_sig_notebook.supports_highres_grayscale() is False
    assert short_sig_notebook.is_realtime_recognition() is False


def test_notebook_n5_dimensions_and_page_lookup_bounds() -> None:
    n5_notebook = Notebook(
        _make_metadata(
            header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N5"},
            pages=[{"PAGEID": "P0"}, {"PAGEID": "P1"}],
        ),
        page_number=1,
    )
    assert (n5_notebook.width, n5_notebook.height) == (
        fileformat.A5X2_PAGE_WIDTH,
        fileformat.A5X2_PAGE_HEIGHT,
    )
    assert n5_notebook.page(1).page_id == "P1"

    with pytest.raises(ValueError, match="loaded with only page_number=1"):
        n5_notebook.page(0)

    with pytest.raises(IndexError, match="page number out of range"):
        n5_notebook.page(2)


# --- Cover, Keyword, Title, Link Domain Property Tests ---


def test_cover_content_attribute() -> None:
    cover = Cover(content=b"cover-bytes")
    assert cover.content == b"cover-bytes"


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


def test_keyword_properties_and_page_number_setter() -> None:
    kw = Keyword(
        {
            "KEYWORDPAGE": "2",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "hello",
        },
        content=b"kw-bytes",
    )
    assert kw.content == b"kw-bytes"
    assert kw.page_number == 1
    assert kw.position_string == "0020"
    assert kw.keyword == "hello"
    assert kw.rect == (10, 20, 40, 60)

    kw.page_number = 4
    assert kw.metadata.page_index == 4
    assert kw.metadata.keyword_page == 5


def test_keyword_missing_rects_raise_parser_exception() -> None:
    kw = Keyword({"KEYWORDPAGE": "1"})
    with pytest.raises(exceptions.ParserException, match="missing KEYWORDRECT"):
        _ = kw.rect
    with pytest.raises(exceptions.ParserException, match="missing KEYWORDRECTORI"):
        _ = kw.position_string


def test_title_properties_and_validation() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid title metadata"):
        Title(cast(Any, None))

    title = Title(
        {"TITLERECTORI": "10,20,30,40", "TITLE": "Heading"},
        content=b"title-bytes",
        page_number=3,
    )
    assert title.content == b"title-bytes"
    assert title.page_number == 3
    assert title.position_string == "00200010"

    title.page_number = 5
    assert title.metadata.page_index == 5

    missing_rect_title = Title({"TITLE": "NoRect"})
    with pytest.raises(exceptions.ParserException, match="missing TITLERECTORI"):
        _ = missing_rect_title.position_string


def test_link_properties_and_validation() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid link metadata"):
        Link(cast(Any, None))

    link = Link(
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
    assert link.content == b"link-bytes"
    assert link.page_number == 2
    assert link.link_type == LinkType.PAGE
    assert link.direction == LinkDirection.OUT
    assert link.position_string == "0015000500350025"
    assert link.rect == (5, 15, 30, 50)
    assert link.timestamp == "987654321"
    assert link.file_path == "encoded_path"
    assert link.file_id == "F123"
    assert link.page_id == "P456"

    link.page_number = 7
    assert link.metadata.page_index == 7

    missing_rect_link = Link({"LINKTYPE": "0"})
    with pytest.raises(exceptions.ParserException, match="missing LINKRECT"):
        _ = missing_rect_link.rect
    with pytest.raises(exceptions.ParserException, match="missing LINKRECT"):
        _ = missing_rect_link.position_string


# --- Page and Layer Domain Property Tests ---


def test_page_rejects_invalid_page_or_layer_metadata() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid page metadata"):
        Page(cast(Any, None))

    with pytest.raises(exceptions.ParserException, match="invalid layer metadata"):
        Page({fileformat.KEY_LAYERS: [cast(Any, None)]})


def test_page_rejects_non_integer_recogn_status() -> None:
    with pytest.raises(exceptions.ParserException, match="RECOGNSTATUS"):
        Page({"RECOGNSTATUS": "bad"})


def test_page_empty_layers_list_and_layer_bounds() -> None:
    empty_layered_page = Page({fileformat.KEY_LAYERS: []})
    assert empty_layered_page.is_layer_supported() is True
    assert empty_layered_page.layers == []
    assert empty_layered_page.protocol is None
    with pytest.raises(IndexError, match="layer number out of range"):
        empty_layered_page.layer(0)


def test_page_properties() -> None:
    layer_info_wire = '[{"layerId"#0,"isBackgroundLayer"#false,"isVisible"#true}]'
    page = Page(
        {
            "PAGEID": "P42",
            "PAGESTYLE": "user_custom",
            "ORIENTATION": "1090",
            "RECOGNSTATUS": "1",
            "LAYERINFO": layer_info_wire,
            "LAYERSEQ": "MAINLAYER,BGLAYER",
            fileformat.KEY_LAYERS: [
                {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"}
            ],
        },
        content=b"c",
        totalpath=b"tp",
        recogn_file=b"rf",
        recogn_text=b"rt",
    )
    assert page.page_id == "P42"
    assert page.style == "user_custom"
    assert page.style_hash == ""
    assert page.orientation == PageOrientation.HORIZONTAL
    assert page.is_horizontal() is True
    assert page.recogn_status == RecognitionStatus.DONE
    assert page.protocol == LayerProtocol.RATTA_RLE
    assert page.layer_order == ["MAINLAYER", "BGLAYER"]
    assert page.layer_info is not None
    assert json.loads(page.layer_info)[0]["layerId"] == 0
    assert page.layer(0).name == LayerName.MAINLAYER
    assert (page.content, page.totalpath, page.recogn_file, page.recogn_text) == (
        b"c",
        b"tp",
        b"rf",
        b"rt",
    )

    page.metadata.style_md5 = "abc123"
    assert page.style_hash == "abc123"


def test_layer_properties() -> None:
    layer = Layer(
        {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE", "LAYERTYPE": "MARK"},
        content=b"layer-bytes",
    )
    assert layer.content == b"layer-bytes"
    assert layer.name == LayerName.MAINLAYER
    assert layer.protocol == LayerProtocol.RATTA_RLE
    assert layer.layer_type == LayerType.MARK


# --- Legacy @deprecated Accessor Backwards-Compatibility Tests ---


def test_supernote_metadata_deprecated_get_total_pages() -> None:
    metadata = _make_metadata(pages=[{"PAGEID": "P1"}])
    with pytest.deprecated_call(match="SupernoteMetadata.total_pages"):
        assert metadata.get_total_pages() == 1  # ty: ignore[deprecated]


def test_notebook_deprecated_getters() -> None:
    metadata = _make_metadata(
        header={"FILE_TYPE": "NOTE", "FILE_ID": "FID99"},
        pages=[{"PAGEID": "P0"}],
    )
    notebook = Notebook(metadata)
    with pytest.deprecated_call():
        assert notebook.get_metadata() is metadata  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_width() == fileformat.PAGE_WIDTH  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_height() == fileformat.PAGE_HEIGHT  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_type() == "note"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_signature() == "SN_FILE_VER_20230015"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_total_pages() == 1  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_page(0) is notebook.pages[0]  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_cover() is notebook.cover  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_keywords() is notebook.keywords  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_titles() is notebook.titles  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_links() is notebook.links  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert notebook.get_fileid() == "FID99"  # ty: ignore[deprecated]


def test_cover_deprecated_accessors() -> None:
    cover = Cover()
    with pytest.deprecated_call():
        cover.set_content(b"cov")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert cover.get_content() == b"cov"  # ty: ignore[deprecated]


def test_keyword_deprecated_accessors() -> None:
    kw = Keyword(
        {
            "KEYWORDPAGE": "2",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "tag",
        }
    )
    with pytest.deprecated_call():
        kw.set_content(b"kw")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert kw.get_content() == b"kw"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert kw.get_page_number() == 1  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert kw.get_position_string() == "0020"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert kw.get_keyword() == "tag"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert kw.get_rect() == (10, 20, 40, 60)  # ty: ignore[deprecated]


def test_title_deprecated_accessors() -> None:
    title = Title({"TITLERECTORI": "10,20,30,40"}, page_number=1)
    with pytest.deprecated_call():
        title.set_content(b"ttl")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert title.get_content() == b"ttl"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        title.set_page_number(4)  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert title.get_page_number() == 4  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert title.get_position_string() == "00200010"  # ty: ignore[deprecated]


def test_link_deprecated_accessors() -> None:
    link = Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "1",
            "LINKRECT": "5,15,25,35",
            "LINKTIMESTAMP": "111",
            "LINKFILE": "path",
            "LINKFILEID": "F1",
            "PAGEID": "P1",
        },
        page_number=0,
    )
    with pytest.deprecated_call():
        link.set_content(b"lnk")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_content() == b"lnk"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        link.set_page_number(3)  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_page_number() == 3  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_type() == Link.TYPE_PAGE_LINK  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_inout() == Link.DIRECTION_IN  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_position_string() == "0015000500350025"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_rect() == (5, 15, 30, 50)  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_timestamp() == "111"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_filepath() == "path"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_fileid() == "F1"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert link.get_pageid() == "P1"  # ty: ignore[deprecated]


def test_page_deprecated_accessors() -> None:
    page = Page(
        {
            "PAGEID": "P9",
            "PAGESTYLE": "style_white",
            "PAGESTYLEMD5": "md5",
            "PROTOCOL": "SN_ASA_COMPRESS",
            "ORIENTATION": "1000",
            "RECOGNSTATUS": "1",
            "LAYERSEQ": "MAINLAYER",
        }
    )
    with pytest.deprecated_call():
        page.set_content(b"pc")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_content() == b"pc"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_layers() == []  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_protocol() == "SN_ASA_COMPRESS"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_style() == "style_white"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_style_hash() == "md5"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_layer_info() is None  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_layer_order() == ["MAINLAYER"]  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        page.set_totalpath(b"tp")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_totalpath() == b"tp"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_pageid() == "P9"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_recogn_status() == Page.RECOGNSTATUS_DONE  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        page.set_recogn_file(b"rf")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_recogn_file() == b"rf"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        page.set_recogn_text(b"rt")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_recogn_text() == b"rt"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert page.get_orientation() == "1000"  # ty: ignore[deprecated]

    layered_page = Page({fileformat.KEY_LAYERS: [{"LAYERNAME": "MAINLAYER"}]})
    with pytest.deprecated_call():
        assert layered_page.get_layer(0) is layered_page.layers[0]  # ty: ignore[deprecated]


def test_layer_deprecated_accessors() -> None:
    layer = Layer(
        {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE", "LAYERTYPE": "NOTE"}
    )
    with pytest.deprecated_call():
        layer.set_content(b"lc")  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert layer.get_content() == b"lc"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert layer.get_name() == "MAINLAYER"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert layer.get_protocol() == "RATTA_RLE"  # ty: ignore[deprecated]
    with pytest.deprecated_call():
        assert layer.get_type() == "NOTE"  # ty: ignore[deprecated]
