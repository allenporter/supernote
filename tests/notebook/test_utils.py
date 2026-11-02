from supernote.notebook import fileformat, utils


def test_workaround_page_wrapper_renames_duplicate_mainlayer_to_bglayer() -> None:
    page_info: fileformat.ParamsBlock = {
        "PAGEID": "P1",
        fileformat.KEY_LAYERS: [
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "LAYER1", "LAYERPROTOCOL": "RATTA_RLE"},
            {},
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
        ],
    }
    wrapped = utils.WorkaroundPageWrapper(page_info)
    assert [layer.name for layer in wrapped.layers] == [
        "MAINLAYER",
        "LAYER1",
        None,
        "BGLAYER",
    ]


def test_workaround_page_wrapper_preserves_distinct_layer_names() -> None:
    page_info: fileformat.ParamsBlock = {
        "PAGEID": "P1",
        fileformat.KEY_LAYERS: [
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "LAYER1", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "BGLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
        ],
    }
    wrapped = utils.WorkaroundPageWrapper(page_info)
    assert [layer.name for layer in wrapped.layers] == [
        "MAINLAYER",
        "LAYER1",
        "BGLAYER",
    ]


def test_workaround_page_wrapper_from_page_copies_page_and_layer_contents() -> None:
    page_info: fileformat.ParamsBlock = {
        "PAGEID": "P1",
        fileformat.KEY_LAYERS: [
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "BGLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
        ],
    }
    page = fileformat.Page(page_info, content=b"page-bytes", totalpath=b"path-bytes")
    page.layer(0).content = b"main-bytes"
    page.layer(1).content = b"bg-bytes"

    wrapped = utils.WorkaroundPageWrapper.from_page(page)
    assert isinstance(wrapped, utils.WorkaroundPageWrapper)
    assert wrapped.content == b"page-bytes"
    assert wrapped.totalpath == b"path-bytes"
    assert [layer.content for layer in wrapped.layers] == [
        b"main-bytes",
        b"bg-bytes",
    ]
