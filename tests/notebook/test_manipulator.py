import copy
import io
from collections.abc import Callable
from unittest.mock import MagicMock, patch

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
    assert (
        reloaded_notebook.get_total_pages()
        == reconstructable_notebook.get_total_pages()
    )
    assert reloaded_notebook.get_width() == reconstructable_notebook.get_width()
    assert reloaded_notebook.get_height() == reconstructable_notebook.get_height()


def test_reconstruct_unsupported_signature(
    sample_notebook: fileformat.Notebook,
) -> None:
    sample_notebook.get_metadata().signature = "SN_SIGNATURE_OLD"
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
    assert (
        merged_notebook.get_total_pages()
        == notebook1.get_total_pages() + notebook2.get_total_pages()
    )


def test_merge_unsupported_signature(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    notebook1.get_metadata().signature = "OLD_SIG"
    with pytest.raises(
        ValueError, match="Only latest file format version is supported"
    ):
        merge(notebook1, notebook2)


def test_merge_mismatched_signatures(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    notebook2.get_metadata().signature = "SN_SIGNATURE_OTHER"
    with pytest.raises(
        ValueError, match="File signature must be same between merging files"
    ):
        merge(notebook1, notebook2)


def test_merge_exceeds_max_pages(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    with patch.object(notebook1, "get_total_pages", return_value=5000):
        with patch.object(notebook2, "get_total_pages", return_value=5000):
            with pytest.raises(
                ValueError, match="The total number of pages are limited to 9999"
            ):
                merge(notebook1, notebook2)


def test_merge_mismatched_header_property(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()

    metadata2 = notebook2.get_metadata()
    assert metadata2.header is not None
    metadata2.header["DEVICE_DPI"] = "999"
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
    orig_pages = reconstructable_notebook.get_total_pages()
    meta = reconstructable_notebook.get_metadata()
    assert meta.pages is not None

    first_page = copy.deepcopy(reconstructable_notebook.get_page(0))
    first_meta_page = copy.deepcopy(meta.pages[0])

    reconstructable_notebook.pages.append(first_page)
    meta.pages.append(first_meta_page)

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.get_total_pages() == orig_pages + 1


def test_notebook_page_deletion(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    merged_bytes = merge(notebook1, notebook2)
    multi_page_nb = load(io.BytesIO(merged_bytes))

    orig_pages = multi_page_nb.get_total_pages()
    assert orig_pages > 1

    meta = multi_page_nb.get_metadata()
    assert meta.pages is not None

    multi_page_nb.pages.pop(0)
    meta.pages.pop(0)

    reconstructed_bytes = reconstruct(multi_page_nb)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.get_total_pages() == orig_pages - 1


def test_notebook_page_reordering(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> None:
    notebook1 = reconstructable_notebook_factory()
    notebook2 = reconstructable_notebook_factory()
    merged_bytes = merge(notebook1, notebook2)
    multi_page_nb = load(io.BytesIO(merged_bytes))

    assert multi_page_nb.get_total_pages() >= 2
    meta = multi_page_nb.get_metadata()
    assert meta.pages is not None

    # Set distinct page IDs and stroke payloads before swapping
    multi_page_nb.pages[0].metadata["PAGEID"] = "PAGE_ZERO"
    multi_page_nb.pages[0].set_totalpath(b"STROKE_ZERO")
    multi_page_nb.pages[1].metadata["PAGEID"] = "PAGE_ONE"
    multi_page_nb.pages[1].set_totalpath(b"STROKE_ONE")

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
    assert reloaded.get_total_pages() == multi_page_nb.get_total_pages()
    assert [
        (reloaded.get_page(0).get_pageid(), reloaded.get_page(0).get_totalpath()),
        (reloaded.get_page(1).get_pageid(), reloaded.get_page(1).get_totalpath()),
    ] == [
        ("PAGE_ONE", b"STROKE_ONE"),
        ("PAGE_ZERO", b"STROKE_ZERO"),
    ]


def test_notebook_layer_changes_and_stroke_manipulation(
    reconstructable_notebook: fileformat.Notebook,
) -> None:
    page = reconstructable_notebook.get_page(0)

    fake_stroke_data = b"STROKE_PATH_BINARY_DATA_TEST"
    page.set_totalpath(fake_stroke_data)
    assert page.get_totalpath() == fake_stroke_data

    if page.is_layer_supported():
        for layer in page.get_layers():
            if layer.get_name() != "BGLAYER":
                layer.set_content(b"MODIFIED_LAYER_CONTENT")

    page.metadata["PAGESTYLE"] = "user_custom_style"
    page.metadata["PAGESTYLEMD5"] = "1234567890abcdef"

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.get_page(0).get_totalpath() == fake_stroke_data


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
    reconstructable_notebook.get_cover().set_content(b"COVER_2_IMAGE_DATA")

    reconstructed_bytes = reconstruct(reconstructable_notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))

    assert reloaded.get_cover().get_content() == b"COVER_2_IMAGE_DATA"
    assert [
        (kw.get_page_number(), kw.get_keyword(), kw.get_rect())
        for kw in reloaded.get_keywords()
    ] == [
        (0, "KW_CONTENT_1", (10, 20, 40, 60)),
        (0, "KW_CONTENT_2", (10, 20, 40, 60)),
    ]
    assert [
        (t.get_page_number(), t.get_position_string(), t.get_content())
        for t in reloaded.get_titles()
    ] == [
        (0, "00200010", b"TITLE_CONTENT_1"),
        (0, "00200010", b"TITLE_CONTENT_2"),
    ]
    assert [
        (link.get_page_number(), link.get_rect(), link.get_content())
        for link in reloaded.get_links()
    ] == [
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
    real_page = notebook.get_page(0)
    for layer in real_page.get_layers():
        if layer.get_name() == "BGLAYER":
            layer.metadata["LAYERNAME"] = "OTHERLAYER"

    assert _find_background_content_from_page(real_page) is None

    notebook2 = reconstructable_notebook_factory()
    real_page2 = notebook2.get_page(0)
    assert _find_background_content_from_page(real_page2) is not None
