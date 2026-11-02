import copy
import io
from collections.abc import Callable
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from supernote.notebook import (
    exceptions,
    fileformat,
    load,
)
from supernote.notebook.manipulator import (
    NotebookBuilder,
    _find_background_content_from_page,
    merge,
    reconstruct,
)
from supernote.notebook.parser import SupernoteXParser
from supernote.notebook.schema import (
    LayerName,
    LayerProtocol,
    LayerType,
)

# --- NotebookBuilder Tests ---


def test_notebook_builder_init_and_getters() -> None:
    builder = NotebookBuilder(offset=100)
    assert builder.get_total_size() == 100
    assert list(builder.get_labels()) == []
    assert builder.get_block_address("nonexistent") == 0
    assert builder.get_duplicate_block_address_list("nonexistent") == [None]


def test_notebook_builder_append_validation() -> None:
    builder = NotebookBuilder()
    with pytest.raises(ValueError, match="empty label or block is not allowed"):
        builder.append("", b"data")
    with pytest.raises(ValueError, match="empty label or block is not allowed"):
        builder.append("LABEL", None)


def test_notebook_builder_append_and_duplicates() -> None:
    builder = NotebookBuilder()

    # Append first block
    res1 = builder.append("BLOCK1", b"hello", skip_block_size=False)
    assert res1 is True
    # 4 bytes size prefix + 5 bytes data = 9 bytes total
    assert builder.get_total_size() == 9
    assert builder.get_block_address("BLOCK1") == 0
    assert builder.get_duplicate_block_address_list("BLOCK1") == [0]

    # Attempt to append duplicate without allow_duplicate
    res_dup_fail = builder.append("BLOCK1", b"world")
    assert res_dup_fail is False

    # Append duplicate with allow_duplicate=True
    res_dup_succ = builder.append("BLOCK1", b"world", allow_duplicate=True)
    assert res_dup_succ is True
    assert builder.get_total_size() == 18
    assert builder.get_block_address("BLOCK1") == 0
    assert builder.get_duplicate_block_address_list("BLOCK1") == [0, 9]

    # Append a third duplicate
    builder.append("BLOCK1", b"again", allow_duplicate=True)
    assert builder.get_duplicate_block_address_list("BLOCK1") == [0, 9, 18]

    # Test skip_block_size
    builder.append("RAW_BLOCK", b"1234", skip_block_size=True)
    assert builder.get_block_address("RAW_BLOCK") == 27


def test_notebook_builder_build_and_dump(capsys: pytest.CaptureFixture[str]) -> None:
    builder = NotebookBuilder()
    builder.append("TEST", b"abc", skip_block_size=True)
    built_bytes = builder.build()
    assert built_bytes == b"abc"

    builder.dump()
    captured = capsys.readouterr()
    assert "# NotebookBuilder Dump:" in captured.out
    assert "total_size = 3" in captured.out


# --- reconstruct Tests ---


def test_reconstruct_valid_notebook(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    reconstructed_bytes = reconstruct(reconstructable_notebook)
    assert isinstance(reconstructed_bytes, bytes)
    assert len(reconstructed_bytes) > 0

    reloaded_notebook = load(io.BytesIO(reconstructed_bytes))
    assert reloaded_notebook.total_pages == reconstructable_notebook.total_pages
    assert reloaded_notebook.width == reconstructable_notebook.width
    assert reloaded_notebook.height == reconstructable_notebook.height


def test_reconstruct_unsupported_signature(
    sample_notebook: fileformat.Notebook,
) -> None:
    sample_notebook.signature = "SN_SIGNATURE_OLD"
    with pytest.raises(
        ValueError, match="Only latest file format version is supported"
    ):
        reconstruct(sample_notebook)


def test_reconstruct_validation_failure(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    with patch.object(
        SupernoteXParser, "parse_stream", side_effect=RuntimeError("Parse error")
    ):
        with pytest.raises(
            exceptions.GeneratedFileValidationException,
            match="generated file fails validation: Parse error",
        ):
            reconstruct(reconstructable_notebook)


# --- merge Tests ---


def test_merge_valid_notebooks(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    merged_bytes = merge(notebook1, notebook2)

    merged_notebook = load(io.BytesIO(merged_bytes))
    assert merged_notebook.total_pages == notebook1.total_pages + notebook2.total_pages


def test_merge_unsupported_signature(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    notebook1.signature = "OLD_SIG"
    with pytest.raises(
        ValueError, match="Only latest file format version is supported"
    ):
        merge(notebook1, notebook2)


def test_merge_mismatched_signatures(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    notebook2.signature = "SN_SIGNATURE_OTHER"
    with pytest.raises(
        ValueError, match="File signature must be same between merging files"
    ):
        merge(notebook1, notebook2)


def test_merge_exceeds_max_pages(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    with patch.object(
        fileformat.Notebook, "total_pages", new_callable=PropertyMock, return_value=5000
    ):
        with pytest.raises(
            ValueError, match="The total number of pages are limited to 9999"
        ):
            merge(notebook1, notebook2)


def test_merge_mismatched_header_property(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()

    notebook2.metadata.header.device_dpi = 999
    with pytest.raises(
        ValueError, match="<DEVICE_DPI> property must be same between merging files"
    ):
        merge(notebook1, notebook2)


def test_merge_validation_failure(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    with patch.object(
        SupernoteXParser, "parse_stream", side_effect=RuntimeError("Merge parse error")
    ):
        with pytest.raises(
            exceptions.GeneratedFileValidationException,
            match="generated file fails validation: Merge parse error",
        ):
            merge(notebook1, notebook2)


# --- Notebook Editing Operations Tests ---


def test_notebook_page_addition(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    orig_pages = reconstructable_notebook.total_pages
    meta = reconstructable_notebook.metadata

    first_page = copy.deepcopy(reconstructable_notebook.page(0))
    first_meta_page = copy.deepcopy(meta.pages[0])

    reconstructable_notebook.pages.append(first_page)
    meta.pages.append(first_meta_page)

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.total_pages == orig_pages + 1


def test_notebook_page_deletion(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    merged_bytes = merge(notebook1, notebook2)
    multi_page_nb = load(io.BytesIO(merged_bytes))

    orig_pages = multi_page_nb.total_pages
    assert orig_pages > 1

    meta = multi_page_nb.metadata
    multi_page_nb.pages.pop(0)
    meta.pages.pop(0)

    reconstructed_bytes = reconstruct(multi_page_nb)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.total_pages == orig_pages - 1


def test_notebook_page_reordering(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    merged_bytes = merge(notebook1, notebook2)
    multi_page_nb = load(io.BytesIO(merged_bytes))

    assert multi_page_nb.total_pages >= 2
    meta = multi_page_nb.metadata

    # Set distinct page IDs and stroke payloads before swapping
    multi_page_nb.pages[0].metadata.page_id = "PAGE_ZERO"
    multi_page_nb.pages[0].totalpath = b"STROKE_ZERO"
    multi_page_nb.pages[1].metadata.page_id = "PAGE_ONE"
    multi_page_nb.pages[1].totalpath = b"STROKE_ONE"

    multi_page_nb.pages[0], multi_page_nb.pages[1] = (
        multi_page_nb.pages[1],
        multi_page_nb.pages[0],
    )
    meta.pages[0], meta.pages[1] = (
        meta.pages[1],
        meta.pages[0],
    )

    reconstructed_bytes = reconstruct(multi_page_nb)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.total_pages == multi_page_nb.total_pages
    assert [
        (reloaded.page(0).page_id, reloaded.page(0).totalpath),
        (reloaded.page(1).page_id, reloaded.page(1).totalpath),
    ] == [
        ("PAGE_ONE", b"STROKE_ONE"),
        ("PAGE_ZERO", b"STROKE_ZERO"),
    ]


def test_notebook_layer_changes_and_stroke_manipulation(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    page = reconstructable_notebook.page(0)

    fake_stroke_data = b"STROKE_PATH_BINARY_DATA_TEST"
    page.totalpath = fake_stroke_data
    assert page.totalpath == fake_stroke_data

    if page.is_layer_supported():
        for layer in page.layers:
            if layer.name != "BGLAYER":
                layer.content = b"MODIFIED_LAYER_CONTENT"

    page.metadata.style = "user_custom_style"
    page.metadata.style_md5 = "1234567890abcdef"

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.page(0).totalpath == fake_stroke_data


def test_notebook_keywords_titles_links_packing(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    kw1 = fileformat.Keyword(
        {
            "KEYWORDPAGE": "1",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "TestKeyword1",
        },
        content=b"KW_CONTENT_1",
    )

    kw2 = fileformat.Keyword(
        {
            "KEYWORDPAGE": "1",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "TestKeyword2",
        },
        content=b"KW_CONTENT_2",
    )

    kw_far = fileformat.Keyword(
        {
            "KEYWORDPAGE": "10000",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "FarKeyword",
        },
        content=b"FAR_KW",
    )

    reconstructable_notebook.keywords = [kw1, kw2, kw_far]

    t1 = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "TestTitle1"},
        content=b"TITLE_CONTENT_1",
        page_number=0,
    )

    t2 = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "TestTitle2"},
        content=b"TITLE_CONTENT_2",
        page_number=0,
    )

    t_far = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "FarTitle"},
        content=b"FAR_TITLE",
        page_number=9999,
    )

    reconstructable_notebook.titles = [t1, t2, t_far]

    l1 = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        },
        content=b"LINK_CONTENT_1",
        page_number=0,
    )

    l2 = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        },
        content=b"LINK_CONTENT_2",
        page_number=0,
    )

    l_far = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        },
        content=b"FAR_LINK",
        page_number=9999,
    )

    reconstructable_notebook.links = [l1, l2, l_far]
    reconstructable_notebook.cover.content = b"COVER_2_IMAGE_DATA"

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))

    assert reloaded.cover.content == b"COVER_2_IMAGE_DATA"
    assert [(kw.page_number, kw.keyword, kw.rect) for kw in reloaded.keywords] == [
        (0, "KW_CONTENT_1", (10, 20, 40, 60)),
        (0, "KW_CONTENT_2", (10, 20, 40, 60)),
    ]
    assert [(t.page_number, t.position_string, t.content) for t in reloaded.titles] == [
        (0, "00200010", b"TITLE_CONTENT_1"),
        (0, "00200010", b"TITLE_CONTENT_2"),
    ]
    assert [(link.page_number, link.rect, link.content) for link in reloaded.links] == [
        (0, (10, 20, 40, 60), b"LINK_CONTENT_1"),
        (0, (10, 20, 40, 60), b"LINK_CONTENT_2"),
    ]


def test_find_background_content_from_page(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    mock_page = MagicMock()
    mock_page.is_layer_supported.return_value = False
    assert _find_background_content_from_page(mock_page) is None

    notebook = reconstructable_notebook_factory()
    real_page = notebook.page(0)
    for layer in real_page.layers:
        if layer.name == "BGLAYER":
            layer.metadata.name = "OTHERLAYER"

    assert _find_background_content_from_page(real_page) is None

    notebook2 = reconstructable_notebook_factory()
    real_page2 = notebook2.page(0)
    assert _find_background_content_from_page(real_page2) is not None


def test_reconstruct_and_merge_reject_missing_metadata(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    object.__setattr__(notebook2, "_metadata", None)

    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        reconstruct(notebook2)

    with pytest.raises(
        exceptions.ParserException, match="notebook metadata is missing"
    ):
        merge(notebook1, notebook2)


def test_reconstruct_is_idempotent_and_preserves_page_layers_metadata(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    first_bytes = reconstruct(reconstructable_notebook)
    second_bytes = reconstruct(reconstructable_notebook)
    assert first_bytes == second_bytes
    assert reconstructable_notebook.page(0).metadata.layers is not None


def test_reconstruct_handles_empty_named_layer_and_user_style_without_md5(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    page = reconstructable_notebook.page(0)
    page.metadata.style = "user_custom"
    page.metadata.style_md5 = None

    # Named layer with None bitmap content should pack as LAYERBITMAP=0
    layer1 = page.layer(1)
    layer1.metadata.name = LayerName.LAYER1
    layer1.metadata.protocol = LayerProtocol.RATTA_RLE
    layer1.metadata.layer_type = LayerType.NOTE
    layer1.content = None

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.page(0).layer(1).content is None


def test_reconstruct_rejects_page_missing_pagestyle(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    reconstructable_notebook.page(0).metadata.style = None

    with pytest.raises(
        exceptions.ManipulatorException, match="page 0 metadata is missing PAGESTYLE"
    ):
        reconstruct(reconstructable_notebook)
