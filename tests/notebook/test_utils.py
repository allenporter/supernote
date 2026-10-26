from supernote.notebook import fileformat, utils


def test_workaround_page_wrapper_deduplicates_mainlayer_and_copies_content() -> None:
    page_info: fileformat.ParamsBlock = {
        "PAGEID": "P1",
        fileformat.KEY_LAYERS: [
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": None, "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "LAYER1", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "LAYER2", "LAYERPROTOCOL": "RATTA_RLE"},
            {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
        ],
    }
    page = fileformat.Page(page_info, content=b"page-content", totalpath=b"total-path")
    page.get_layer(0).set_content(b"main-layer-bytes")
    page.get_layer(4).set_content(b"bg-layer-bytes")

    wrapped = utils.WorkaroundPageWrapper.from_page(page)

    assert wrapped.get_content() == b"page-content"
    assert wrapped.get_totalpath() == b"total-path"
    assert [layer.get_name() for layer in wrapped.get_layers()] == [
        "MAINLAYER",
        None,
        "LAYER1",
        "LAYER2",
        "BGLAYER",
    ]
    assert wrapped.get_layer(0).get_content() == b"main-layer-bytes"
    assert wrapped.get_layer(4).get_content() == b"bg-layer-bytes"
