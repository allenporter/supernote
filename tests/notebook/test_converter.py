import base64
import io
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops
from syrupy.extensions.image import PNGImageSnapshotExtension

from supernote.notebook import (
    ColorPalette,
    ImageConverter,
    PdfConverter,
    PngConverter,
    SvgConverter,
    TextConverter,
    VisibilityOverlay,
    fileformat,
    load_notebook,
)
from supernote.notebook.color import (
    MODE_RGB,
    RGB_BLACK,
    RGB_DARK_GRAY,
    RGB_GRAY,
    RGB_WHITE,
)
from supernote.notebook.converter import build_visibility_overlay
from supernote.notebook.decoder import TextElement

# Find all test note paths dynamically under tests/testdata/
TEST_DATA_DIR = Path(__file__).parent.parent / "testdata"
NOTE_PATHS = sorted(TEST_DATA_DIR.glob("**/*.note"))
SAMPLE_NOTE_PATH = TEST_DATA_DIR / "20251207_221454.note"
STROLLER_NOTE_PATH = TEST_DATA_DIR / "mmujynya" / "stroller.note"
HORIZONTAL_NOTE_PATH = TEST_DATA_DIR / "philips" / "horizontal_1090.note"


@lru_cache(maxsize=32)
def get_cached_notebook(note_path_str: str):
    return load_notebook(note_path_str)


class VisualPngSnapshotExtension(PNGImageSnapshotExtension):
    """Custom syrupy extension that stores snapshots as raw PNG files

    but compares them using pixel data difference (ImageChops) to be robust
    across different platforms and zlib/Pillow library versions.
    """

    def matches(self, *, serialized_data, snapshot_data) -> bool:
        if not serialized_data or not snapshot_data:
            return False
        try:
            img_new = Image.open(io.BytesIO(serialized_data))
            img_golden = Image.open(io.BytesIO(snapshot_data))

            # Compare dimensions and mode first
            if img_new.size != img_golden.size or img_new.mode != img_golden.mode:
                return False

            # Compare actual visual pixel data difference
            diff = ImageChops.difference(img_new, img_golden).getbbox()
            return diff is None
        except Exception:
            return False


def _serialize_notebook_metadata(notebook) -> dict:
    """Extract structural metadata that is serializable and useful for regression checks."""
    return {
        "type": notebook.get_type(),
        "signature": notebook.get_signature(),
        "width": notebook.get_width(),
        "height": notebook.get_height(),
        "total_pages": notebook.get_total_pages(),
        "keywords": [kw.metadata for kw in notebook.get_keywords()],
        "titles": [t.metadata for t in notebook.get_titles()],
        "links": [link.metadata for link in notebook.get_links()],
    }


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_metadata_snapshot(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    metadata_snapshot = _serialize_notebook_metadata(notebook)

    # Assert against syrupy snapshot (default text serializer)
    assert metadata_snapshot == snapshot


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_png_snapshots(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    converter = PngConverter(notebook)
    total_pages = notebook.get_total_pages()

    # Convert and snapshot each page visually using the custom visual diff extension
    for p in range(total_pages):
        img = converter.convert(p)

        # Save image as PNG in-memory bytes with fast compression for testing
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)
        png_bytes = buf.getvalue()

        # Assert bytes against syrupy using the custom visual diff extension
        assert png_bytes == snapshot(
            name=f"page_{p}", extension_class=VisualPngSnapshotExtension
        )


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_text_snapshots(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    texts = {}
    if notebook.is_realtime_recognition():
        converter = TextConverter(notebook)
        total_pages = notebook.get_total_pages()

        # Extract text from all pages
        for p in range(total_pages):
            texts[f"page_{p}"] = converter.convert(p)

    assert texts == snapshot


def test_text_converter_formatting() -> None:
    # Create mock notebook and page
    class MockPage:
        def get_recogn_status(self):
            return 1  # RECOGNSTATUS_DONE

        def get_recogn_text(self):
            return b"dummy_binary"

    class MockNotebook:
        def is_realtime_recognition(self):
            return True

        def get_page(self, page_number):
            return MockPage()

    # Mock decoder returning text elements at different y-coordinates
    elements = [
        TextElement(label="Hello", y=10),
        TextElement(label="world", y=12),  # gap <= 3 -> space
        TextElement(label="!", y=12),  # punctuation cleanup -> "world!"
        TextElement(label="This is a new line", y=20),  # gap > 3 -> newline
        TextElement(
            label=" ( with parens ) ", y=20
        ),  # punctuation cleanup -> "(with parens)"
    ]

    with patch("supernote.notebook.decoder.TextDecoder.decode", return_value=elements):
        converter = TextConverter(cast(Any, MockNotebook()))
        result = converter.convert(0)

    assert result == "Hello world!\nThis is a new line (with parens)"


def test_text_converter_edge_cases() -> None:
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    converter = TextConverter(notebook)

    # non-realtime notebook returns None
    assert converter.convert(0) is None

    # status != RECOGNSTATUS_DONE
    with patch.object(notebook, "is_realtime_recognition", return_value=True):
        with patch.object(notebook.get_page(0), "get_recogn_status", return_value=0):
            assert converter.convert(0) is None

    # decode returns None
    with patch.object(notebook, "is_realtime_recognition", return_value=True):
        with patch.object(notebook.get_page(0), "get_recogn_status", return_value=1):
            with patch(
                "supernote.notebook.decoder.TextDecoder.decode", return_value=None
            ):
                assert converter.convert(0) is None


def test_get_layer_visibility_base64() -> None:
    # base64 encoded string of:
    # '[{"layerId": 0, "isBackgroundLayer": false, "isVisible": true}]'
    base64_layer_info = "W3sibGF5ZXJJZCI6IDAsICJpc0JhY2tncm91bmRMYXllciI6IGZhbHNlLCAiaXNWaXNpYmxlIjogdHJ1ZX1d"

    class MockPage:
        def get_layer_info(self):
            return base64_layer_info

    class DummyNotebook:
        pass

    converter = ImageConverter(DummyNotebook())

    # We call the internal _get_layer_visibility method
    visibility = converter._get_layer_visibility(MockPage())

    assert visibility == {"MAINLAYER": True}


# --- SVG Converter Tests ---


def test_svg_converter_export() -> None:
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    converter = SvgConverter(notebook)
    svg_str = converter.convert(0)
    assert isinstance(svg_str, str)
    assert svg_str.startswith("<svg") or "<svg" in svg_str
    assert "</svg>" in svg_str


def test_svg_converter_horizontal_and_visibility() -> None:
    notebook = load_notebook(str(HORIZONTAL_NOTE_PATH))
    custom_palette = ColorPalette(
        MODE_RGB,
        (RGB_BLACK, RGB_DARK_GRAY, RGB_GRAY, RGB_WHITE),
    )
    converter = SvgConverter(notebook, palette=custom_palette)

    # Test with background invisible
    vo_invisible_bg = build_visibility_overlay(background=VisibilityOverlay.INVISIBLE)
    svg_str = converter.convert(0, visibility_overlay=vo_invisible_bg)
    assert isinstance(svg_str, str)
    assert "<svg" in svg_str


# --- PDF Converter Tests ---


def test_pdf_converter_basic_export() -> None:
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    pdf_converter = PdfConverter(notebook)

    # Single page export
    pdf_bytes = pdf_converter.convert(0)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")

    # All pages export (-1)
    all_pdf_bytes = pdf_converter.convert(-1)
    assert isinstance(all_pdf_bytes, bytes)
    assert all_pdf_bytes.startswith(b"%PDF-")

    # List of page indices
    list_pdf_bytes = pdf_converter.convert([0])
    assert isinstance(list_pdf_bytes, bytes)
    assert list_pdf_bytes.startswith(b"%PDF-")


def test_pdf_converter_keywords_and_landscape() -> None:
    # stroller.note has keywords
    notebook = load_notebook(str(STROLLER_NOTE_PATH))
    pdf_converter = PdfConverter(notebook)

    pdf_bytes = pdf_converter.convert(0, enable_keyword=True)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")

    # Horizontal (landscape) notebook
    horiz_nb = load_notebook(str(HORIZONTAL_NOTE_PATH))
    horiz_pdf_converter = PdfConverter(horiz_nb)
    horiz_pdf_bytes = horiz_pdf_converter.convert(0)
    assert horiz_pdf_bytes.startswith(b"%PDF-")


def test_pdf_converter_links() -> None:
    notebook = load_notebook(str(SAMPLE_NOTE_PATH))
    page0 = notebook.get_page(0)
    page0.metadata["PAGEID"] = "P0001"

    # Add mock internal page link, web link, and incoming link
    web_url_b64 = base64.b64encode(b"https://example.com").decode()
    l_internal = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "test.note",
            "LINKFILEID": str(notebook.get_fileid()),
            "PAGEID": "P0001",
        }
    )
    l_internal.set_page_number(0)

    l_web = fileformat.Link(
        {
            "LINKTYPE": "4",
            "LINKINOUT": "0",
            "LINKRECT": "50,60,70,80",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": web_url_b64,
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
    )
    l_web.set_page_number(0)

    l_in = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "1",  # DIRECTION_IN (should be ignored)
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "test.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
    )
    l_in.set_page_number(0)

    notebook.links = [l_internal, l_web, l_in]

    pdf_converter = PdfConverter(notebook)
    pdf_bytes = pdf_converter.convert(0, enable_link=True)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
