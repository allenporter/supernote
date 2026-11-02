"""Unit tests for supernote.testing.notebook_fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from supernote.server.utils.note_content import infer_page_date
from supernote.server.utils.paths import is_valid_page_id
from supernote.testing import (
    append_synthetic_page,
    build_synthetic_notebook,
)


def test_build_synthetic_notebook_pages_dates_and_ground_truth(tmp_path: Path) -> None:
    base = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    synth = build_synthetic_notebook(
        pages=[
            "# Day One\n\n- [x] Calibrate sensor #lab",
            "# Day Two\n\n- [ ] Analyze spectrum #optics",
        ],
        hidden_layer_pages={0: "### Lab Coach\n- Check dark current"},
        base_date=base,
        seed=15,
    )
    assert len(synth.pages) == 2
    assert is_valid_page_id(synth.pages[0].page_id)
    assert is_valid_page_id(synth.pages[1].page_id)
    assert infer_page_date(synth.pages[0].page_id) == datetime(2026, 4, 1)
    assert infer_page_date(synth.pages[1].page_id) == datetime(2026, 4, 2)
    assert synth.pages[0].headings == ("Day One",)
    assert synth.pages[0].keywords == ("lab",)
    assert "Calibrate sensor" in synth.full_text
    assert "Analyze spectrum" in synth.full_text

    out_path = synth.write_to(tmp_path / "sub" / "fixture.note")
    assert out_path.is_file()
    nb = synth.load()
    assert nb.total_pages == 2

    updated = append_synthetic_page(
        synth,
        "# Day Three\n\n- [x] Publish report #release",
    )
    assert len(updated.pages) == 3
    assert updated.pages[0].page_id == synth.pages[0].page_id
    assert infer_page_date(updated.pages[2].page_id) == datetime(2026, 4, 3)


def test_build_synthetic_notebook_free_flowing_markdown_and_validation() -> None:
    synth_md = build_synthetic_notebook(
        markdown="# Free Flow\n\n---\n\n## Second Page",
        style="stylized",
        background="dots",
    )
    assert len(synth_md.pages) == 2

    synth_default = build_synthetic_notebook()
    assert len(synth_default.pages) == 1
    assert "Test Note" in synth_default.full_text

    with pytest.raises(ValueError, match="Specify either `pages` or `markdown`"):
        build_synthetic_notebook(pages=["# A"], markdown="# B")
