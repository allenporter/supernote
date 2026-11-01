import json
from typing import Any, cast

import pytest

from supernote.notebook import (
    Keyword,
    Notebook,
    Page,
    SupernoteMetadata,
    exceptions,
    fileformat,
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


def test_supernote_metadata_construction_and_serialization() -> None:
    metadata = _make_metadata(pages=[{"PAGEID": "P1", "__layers__": []}])
    assert metadata.type == "note"
    assert metadata.signature == "SN_FILE_VER_20230015"
    assert metadata.get_total_pages() == 1
    assert metadata.is_layer_supported(0) is True

    with pytest.raises(IndexError, match="page number out of range"):
        metadata.is_layer_supported(1)

    serialized = json.loads(metadata.to_json(indent=2))
    assert serialized == {
        "__type__": "note",
        "__signature__": "SN_FILE_VER_20230015",
        "__header__": {"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        "__footer__": {},
        "__pages__": [{"PAGEID": "P1", "__layers__": []}],
    }


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


def test_notebook_validates_metadata_and_page_entries() -> None:
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        Notebook(cast(Any, None))

    bad_pages_metadata = _make_metadata(pages=[cast(Any, None)])
    with pytest.raises(exceptions.ParserException, match="invalid page metadata entry"):
        Notebook(bad_pages_metadata)

    notebook = Notebook(_make_metadata())
    assert notebook.get_type() == "note"
    assert notebook.get_signature() == "SN_FILE_VER_20230015"
    assert notebook.get_total_pages() == 0
    assert notebook.supports_highres_grayscale() is True

    short_sig_notebook = Notebook(_make_metadata(signature="SHORT"))
    assert short_sig_notebook.supports_highres_grayscale() is False

    object.__setattr__(notebook, "metadata", None)
    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        notebook.get_metadata()


def test_keyword_validates_page_metadata() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid keyword metadata"):
        Keyword(cast(Any, None))

    with pytest.raises(exceptions.ParserException, match="missing KEYWORDPAGE"):
        Keyword({})

    with pytest.raises(exceptions.ParserException, match="invalid KEYWORDPAGE"):
        Keyword({"KEYWORDPAGE": "not-an-int"})


def test_page_metadata_accessors_and_guards() -> None:
    with pytest.raises(exceptions.ParserException, match="invalid page metadata"):
        Page(cast(Any, None))

    with pytest.raises(exceptions.ParserException, match="invalid layer metadata"):
        Page({fileformat.KEY_LAYERS: [cast(Any, None)]})

    # Partial or empty layers list does not raise IndexError
    empty_layered_page = Page({fileformat.KEY_LAYERS: []})
    assert empty_layered_page.is_layer_supported() is True
    assert empty_layered_page.get_layers() == []
    assert empty_layered_page.get_protocol() is None

    page = Page({"PAGESTYLE": "user_custom"})
    assert page.get_style() == "user_custom"
    assert page.get_style_hash() == ""
    assert page.get_layer_info() is None
    assert page.get_layer_order() == []
    assert page.get_recogn_status() == Page.RECOGNSTATUS_NONE

    page.metadata["PAGESTYLEMD5"] = "0"
    assert page.get_style_hash() == ""
    page.metadata["PAGESTYLEMD5"] = "abc123"
    assert page.get_style_hash() == "abc123"

    page.metadata["RECOGNSTATUS"] = "bad"
    with pytest.raises(exceptions.ParserException, match="invalid page RECOGNSTATUS"):
        page.get_recogn_status()
