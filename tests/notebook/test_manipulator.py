import copy
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from supernote.notebook import (
    exceptions,
    fileformat,
    load,
    load_notebook,
)
from supernote.notebook.manipulator import (
    NotebookBuilder,
    _find_background_content_from_page,
    _verify_header_property,
    merge,
    reconstruct,
)
from supernote.notebook.parser import SupernoteXParser

TEST_DATA_DIR = Path(__file__).parent.parent / "testdata"
SAMPLE_NOTE_PATH = TEST_DATA_DIR / "20251207_221454.note"
PHILIPS_TEST_NOTE = TEST_DATA_DIR / "philips" / "test.note"
LATEST_SIG = SupernoteXParser.SN_SIGNATURES[-1]


def _prepare_notebook_for_reconstruct(
    notebook: fileformat.Notebook,
) -> fileformat.Notebook:
    """Update signature to latest supported signature so reconstruct/merge can proceed."""
    notebook.get_metadata().signature = LATEST_SIG
    return notebook


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
    # Previous total_size was 9. New block: 4 bytes size + 5 bytes data = 9 bytes.
    # Total size becomes 18.
    assert builder.get_total_size() == 18
    assert builder.get_block_address("BLOCK1") == 0  # returns first address
    assert builder.get_duplicate_block_address_list("BLOCK1") == [0, 9]

    # Append a third duplicate
    builder.append("BLOCK1", b"again", allow_duplicate=True)
    assert builder.get_duplicate_block_address_list("BLOCK1") == [0, 9, 18]

    # Test skip_block_size
    builder.append("RAW_BLOCK", b"1234", skip_block_size=True)
    # Total size increased by 4 bytes (len of b"1234") without length field
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


def test_reconstruct_valid_notebook() -> None:
    notebook = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    reconstructed_bytes = reconstruct(notebook)
    assert isinstance(reconstructed_bytes, bytes)
    assert len(reconstructed_bytes) > 0

    # Parse reconstructed binary stream to verify integrity
    stream = io.BytesIO(reconstructed_bytes)
    reloaded_notebook = load(stream)
    assert reloaded_notebook.get_total_pages() == notebook.get_total_pages()
    assert reloaded_notebook.get_width() == notebook.get_width()
    assert reloaded_notebook.get_height() == notebook.get_height()


def test_reconstruct_unsupported_signature() -> None:
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    metadata = notebook.get_metadata()
    metadata.signature = "SN_SIGNATURE_OLD"
    with pytest.raises(
        ValueError, match="Only latest file format version is supported"
    ):
        reconstruct(notebook)


def test_reconstruct_validation_failure() -> None:
    notebook = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))

    # Mock SupernoteXParser.parse_stream to raise an exception during validation
    with patch.object(
        SupernoteXParser, "parse_stream", side_effect=RuntimeError("Parse error")
    ):
        with pytest.raises(
            exceptions.GeneratedFileValidationException,
            match="generated file fails validation: Parse error",
        ):
            reconstruct(notebook)


# --- merge Tests ---


def test_merge_valid_notebooks() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    merged_bytes = merge(notebook1, notebook2)
    assert isinstance(merged_bytes, bytes)

    stream = io.BytesIO(merged_bytes)
    merged_notebook = load(stream)
    assert (
        merged_notebook.get_total_pages()
        == notebook1.get_total_pages() + notebook2.get_total_pages()
    )


def test_merge_unsupported_signature() -> None:
    notebook1 = load_notebook(str(SAMPLE_NOTE_PATH))
    notebook2 = load_notebook(str(SAMPLE_NOTE_PATH))
    notebook1.get_metadata().signature = "OLD_SIG"
    with pytest.raises(
        ValueError, match="Only latest file format version is supported"
    ):
        merge(notebook1, notebook2)


def test_merge_mismatched_signatures() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = load_notebook(str(SAMPLE_NOTE_PATH))
    notebook2.get_metadata().signature = "SN_SIGNATURE_OTHER"
    with pytest.raises(
        ValueError, match="File signature must be same between merging files"
    ):
        merge(notebook1, notebook2)


def test_merge_exceeds_max_pages() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    with patch.object(notebook1, "get_total_pages", return_value=5000):
        with patch.object(notebook2, "get_total_pages", return_value=5000):
            with pytest.raises(
                ValueError, match="The total number of pages are limited to 9999"
            ):
                merge(notebook1, notebook2)


def test_merge_mismatched_header_property() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))

    metadata2 = notebook2.get_metadata()
    assert metadata2.header is not None
    metadata2.header["DEVICE_DPI"] = "999"
    with pytest.raises(
        ValueError, match="<DEVICE_DPI> property must be same between merging files"
    ):
        merge(notebook1, notebook2)


def test_merge_validation_failure() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    with patch.object(
        SupernoteXParser, "parse_stream", side_effect=RuntimeError("Merge parse error")
    ):
        with pytest.raises(
            exceptions.GeneratedFileValidationException,
            match="generated file fails validation: Merge parse error",
        ):
            merge(notebook1, notebook2)


def test_verify_header_property_helper() -> None:
    m1 = MagicMock()
    m2 = MagicMock()
    m1.header = {"FILE_TYPE": "NOTE"}
    m2.header = {"FILE_TYPE": "MARK"}
    with pytest.raises(
        ValueError, match="<FILE_TYPE> property must be same between merging files"
    ):
        _verify_header_property("FILE_TYPE", m1, m2)


# --- Notebook Editing Operations Tests ---


def test_notebook_page_addition() -> None:
    notebook = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    orig_pages = notebook.get_total_pages()
    meta = notebook.get_metadata()
    assert meta.pages is not None

    # Duplicate first page and add to pages list & metadata
    first_page = copy.deepcopy(notebook.get_page(0))
    first_meta_page = copy.deepcopy(meta.pages[0])

    notebook.pages.append(first_page)
    meta.pages.append(first_meta_page)

    reconstructed_bytes = reconstruct(notebook)
    stream = io.BytesIO(reconstructed_bytes)
    reloaded = load(stream)
    assert reloaded.get_total_pages() == orig_pages + 1


def test_notebook_page_deletion() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    merged_bytes = merge(notebook1, notebook2)
    stream = io.BytesIO(merged_bytes)
    multi_page_nb = load(stream)

    orig_pages = multi_page_nb.get_total_pages()
    assert orig_pages > 1

    meta = multi_page_nb.get_metadata()
    assert meta.pages is not None

    # Delete first page
    multi_page_nb.pages.pop(0)
    meta.pages.pop(0)

    reconstructed_bytes = reconstruct(multi_page_nb)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.get_total_pages() == orig_pages - 1


def test_notebook_page_reordering() -> None:
    notebook1 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    notebook2 = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    merged_bytes = merge(notebook1, notebook2)
    multi_page_nb = load(io.BytesIO(merged_bytes))

    assert multi_page_nb.get_total_pages() >= 2
    meta = multi_page_nb.get_metadata()
    assert meta.pages is not None

    # Swap first two pages
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


def test_notebook_layer_changes_and_stroke_manipulation() -> None:
    notebook = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))
    page = notebook.get_page(0)

    # Stroke manipulation: set totalpath block
    fake_stroke_data = b"STROKE_PATH_BINARY_DATA_TEST"
    page.set_totalpath(fake_stroke_data)
    assert page.get_totalpath() == fake_stroke_data

    # Modify layer contents
    if page.is_layer_supported():
        layers = page.get_layers()
        for layer in layers:
            if layer.get_name() != "BGLAYER":
                layer.set_content(b"MODIFIED_LAYER_CONTENT")

    # Set user background style to test user_ style hash packing
    page.metadata["PAGESTYLE"] = "user_custom_style"
    page.metadata["PAGESTYLEMD5"] = "1234567890abcdef"

    reconstructed_bytes = reconstruct(notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert reloaded.get_page(0).get_totalpath() == fake_stroke_data


def test_notebook_keywords_titles_links_packing() -> None:
    notebook = _prepare_notebook_for_reconstruct(load_notebook(str(SAMPLE_NOTE_PATH)))

    # Add keywords
    kw1 = fileformat.Keyword(
        {
            "KEYWORDPAGE": "1",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "TestKeyword1",
        }
    )
    kw1.set_content(b"KW_CONTENT_1")

    kw2 = fileformat.Keyword(
        {
            "KEYWORDPAGE": "1",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "TestKeyword2",
        }
    )
    kw2.set_content(b"KW_CONTENT_2")

    kw_far = fileformat.Keyword(
        {
            "KEYWORDPAGE": "10000",
            "KEYWORDRECTORI": "10,20,30,40",
            "KEYWORDRECT": "10,20,30,40",
            "KEYWORD": "FarKeyword",
        }
    )
    kw_far.set_content(b"FAR_KW")

    notebook.keywords = [kw1, kw2, kw_far]

    # Add titles (with duplicates on same position string)
    t1 = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "TestTitle1"}
    )
    t1.set_page_number(0)
    t1.set_content(b"TITLE_CONTENT_1")

    t2 = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "TestTitle2"}
    )
    t2.set_page_number(0)
    t2.set_content(b"TITLE_CONTENT_2")

    t_far = fileformat.Title(
        {"TITLERECTORI": "10,20,30,40", "TITLEBITMAP": "0", "TITLE": "FarTitle"}
    )
    t_far.set_page_number(9999)
    t_far.set_content(b"FAR_TITLE")

    notebook.titles = [t1, t2, t_far]

    # Add links (with duplicates and far page > 9999)
    l1 = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
    )
    l1.set_page_number(0)
    l1.set_content(b"LINK_CONTENT_1")

    l2 = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
    )
    l2.set_page_number(0)
    l2.set_content(b"LINK_CONTENT_2")

    l_far = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "file.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
    )
    l_far.set_page_number(9999)
    l_far.set_content(b"FAR_LINK")

    notebook.links = [l1, l2, l_far]

    # Set cover content
    notebook.get_cover().set_content(b"COVER_2_IMAGE_DATA")

    reconstructed_bytes = reconstruct(notebook)
    reloaded = load(io.BytesIO(reconstructed_bytes))
    assert len(reloaded.get_keywords()) >= 2
    assert len(reloaded.get_titles()) >= 2


def test_find_background_content_from_page() -> None:
    # Non-layered page wrapper / page returns None
    mock_page = MagicMock()
    mock_page.is_layer_supported.return_value = False
    assert _find_background_content_from_page(mock_page) is None

    # Page with layers but no BGLAYER returns None
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    real_page = notebook.get_page(0)
    for layer in real_page.get_layers():
        if layer.get_name() == "BGLAYER":
            layer.metadata["LAYERNAME"] = "OTHERLAYER"

    assert _find_background_content_from_page(real_page) is None

    # Page with BGLAYER returns its content
    notebook2 = load_notebook(str(SAMPLE_NOTE_PATH))
    real_page2 = notebook2.get_page(0)

    bg_content = _find_background_content_from_page(real_page2)
    assert bg_content is not None
