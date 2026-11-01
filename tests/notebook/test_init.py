import subprocess
import sys

import pytest

import supernote
import supernote.notebook as notebook_pkg


def test_top_level_package_lazy_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, supernote; assert 'supernote.server' not in sys.modules; assert 'supernote.client' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert supernote.notebook is not None
    with pytest.raises(AttributeError):
        _ = supernote.nonexistent_submodule


def test_notebook_package_exports() -> None:
    expected_exports = {
        "MODE_RGB",
        "ColorPalette",
        "Cover",
        "ImageConverter",
        "Keyword",
        "Layer",
        "Link",
        "Notebook",
        "Page",
        "PdfConverter",
        "PngConverter",
        "SupernoteMetadata",
        "SvgConverter",
        "TextConverter",
        "Title",
        "VisibilityOverlay",
        "load",
        "load_notebook",
        "merge",
        "parse_metadata",
        "parse_notebook",
        "reconstruct",
    }
    assert set(notebook_pkg.__all__) == expected_exports
    for name in expected_exports:
        assert hasattr(notebook_pkg, name)
