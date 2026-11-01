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
    assert [layer.get_name() for layer in wrapped.get_layers()] == [
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
    assert [layer.get_name() for layer in wrapped.get_layers()] == [
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
    page = fileformat.Page(page_info)
    page.set_content(b"page-bytes")
    page.set_totalpath(b"path-bytes")
    page.get_layer(0).set_content(b"main-bytes")
    page.get_layer(1).set_content(b"bg-bytes")

    wrapped = utils.WorkaroundPageWrapper.from_page(page)
    assert isinstance(wrapped, utils.WorkaroundPageWrapper)
    assert wrapped.get_content() == b"page-bytes"
    assert wrapped.get_totalpath() == b"path-bytes"
    assert [layer.get_content() for layer in wrapped.get_layers()] == [
        b"main-bytes",
        b"bg-bytes",
    ]
