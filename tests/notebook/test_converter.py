import io
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops
from syrupy.extensions.image import PNGImageSnapshotExtension

from supernote.notebook import (
    ImageConverter,
    PngConverter,
    TextConverter,
    load_notebook,
)
from supernote.notebook.decoder import TextElement

# Find all test note paths dynamically under tests/testdata/
TEST_DATA_DIR = Path(__file__).parent.parent / "testdata"
NOTE_PATHS = sorted(TEST_DATA_DIR.glob("**/*.note"))


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
