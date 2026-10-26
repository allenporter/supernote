"""Shared fixtures and fakes for notebook tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from supernote.notebook import fileformat, load_notebook
from supernote.notebook.parser import SupernoteXParser

TEST_DATA_DIR = Path(__file__).parent.parent / "testdata"
SAMPLE_NOTE_PATH = TEST_DATA_DIR / "20251207_221454.note"
STROLLER_NOTE_PATH = TEST_DATA_DIR / "mmujynya" / "stroller.note"
HORIZONTAL_NOTE_PATH = TEST_DATA_DIR / "philips" / "horizontal_1090.note"
ONE_TO_TEN_NOTE_PATH = TEST_DATA_DIR / "philips" / "1to10.note"
LATEST_SIG = SupernoteXParser.SN_SIGNATURES[-1]


class FakeDecoder:
    """Configurable fake decoder returning a fixed (bitmap, size, bpp) tuple."""

    def __init__(
        self, bitmap: bytes, size: tuple[int, int] = (1, 1), bpp: int = 8
    ) -> None:
        self._bitmap = bitmap
        self._size = size
        self._bpp = bpp

    def decode(
        self, binary: bytes, width: int, height: int, **kwargs: Any
    ) -> tuple[bytes, tuple[int, int], int]:
        return self._bitmap, self._size, self._bpp


@pytest.fixture
def sample_notebook() -> fileformat.Notebook:
    """Return a freshly loaded sample Notebook."""
    return load_notebook(str(SAMPLE_NOTE_PATH))


@pytest.fixture
def reconstructable_notebook_factory() -> Callable[[], fileformat.Notebook]:
    """Return a factory producing sample Notebooks upgraded to the latest signature."""

    def _create() -> fileformat.Notebook:
        notebook = load_notebook(str(SAMPLE_NOTE_PATH))
        notebook.get_metadata().signature = LATEST_SIG
        return notebook

    return _create


@pytest.fixture
def reconstructable_notebook(
    reconstructable_notebook_factory: Callable[[], fileformat.Notebook],
) -> fileformat.Notebook:
    """Return a sample Notebook upgraded to the latest signature for reconstruct/merge."""
    return reconstructable_notebook_factory()


@pytest.fixture
def make_notebook() -> Callable[..., fileformat.Notebook]:
    """Build a lightweight synthetic Notebook with configurable header/pages."""

    def _make(
        *,
        signature: str = LATEST_SIG,
        header: dict[str, str] | None = None,
        pages: list[fileformat.ParamsBlock] | None = None,
        footer: dict[str, Any] | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> fileformat.Notebook:
        meta = fileformat.SupernoteMetadata(
            type="note",
            signature=signature,
            header=header or {"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
            footer=footer or {"FILE_FEATURE": "24"},
            pages=(
                pages
                if pages is not None
                else [{"PAGEID": "P1", "RECOGNSTATUS": "0", "PROTOCOL": "RATTA_RLE"}]
            ),
        )
        return fileformat.Notebook(meta, page_width=width, page_height=height)

    return _make
