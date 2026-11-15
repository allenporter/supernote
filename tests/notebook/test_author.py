"""Unit and round-trip binary tests for supernote.notebook.author."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from supernote.notebook import (
    ImageConverter,
    PdfConverter,
    SvgConverter,
    TextConverter,
    VisibilityOverlay,
    fileformat,
    load,
    load_notebook,
)
from supernote.notebook.author import (
    ExtraLayerSpec,
    NotebookAuthor,
    create_notebook,
    generate_supernote_id,
)
from supernote.notebook.converter import build_visibility_overlay
from supernote.notebook.decoder import RattaRleX2Decoder
from supernote.notebook.renderer import BackgroundStyle, RenderStyle

_ID_FORMAT_RE = re.compile(r"^[FP]\d{20}[A-Za-z0-9]{12}$")


def test_generate_supernote_id_format_and_validation() -> None:
    ts = datetime(2026, 3, 10, 8, 30, 15, 123456, tzinfo=UTC)
    fid = generate_supernote_id("F", ts)
    pid = generate_supernote_id("P", ts)
    assert _ID_FORMAT_RE.fullmatch(fid)
    assert _ID_FORMAT_RE.fullmatch(pid)
    assert pid.startswith("P20260310083015123456")

    with pytest.raises(ValueError, match="prefix must be 'F' or 'P'"):
        generate_supernote_id("X")


def test_stylized_markdown_multi_page_toc_keywords_and_links() -> None:
    md = """# Sprint Roadmap

> Ship programmatic `.note` authoring cleanly.

- [x] Implement `RattaRleX2Encoder` #encoder
- [ ] Add CLI `supernote create` #cli

| Component | Target |
| --------- | ------ |
| Author | supernote.notebook |
| Fixture | supernote.testing |

Jump to [Page Two](page:2), [Next](page:+1), or read [Supernote Docs](https://supernote.com).

---

## Page Two Details

1. Verify TOC titles and [Back](page:-1)
2. Verify internal and web links #links
"""
    dt_p1 = datetime(2026, 3, 10, 8, 30, tzinfo=UTC)
    dt_p2 = datetime(2026, 3, 11, 9, 15, tzinfo=UTC)

    author = NotebookAuthor(equipment="N6", seed=12)
    pages = author.add_markdown(
        md,
        style=RenderStyle.STYLIZED,
        background=BackgroundStyle.RULED,
        auto_toc=True,
        extract_keywords=True,
        page_dates=[dt_p1, dt_p2],
    )
    assert len(pages) == 2
    assert pages[0].page_id.startswith("P20260310083000")
    assert pages[1].page_id.startswith("P20260311091500")

    # to_bytes() is pure and idempotent across repeated invocations
    first_bytes = author.to_bytes()
    second_bytes = author.to_bytes()
    assert first_bytes == second_bytes

    nb = load(io.BytesIO(first_bytes))
    assert nb.total_pages == 2
    assert nb.page(0).style == "user_stylized"

    titles = nb.titles
    assert len(titles) == 2
    assert titles[0].page_number == 0
    assert titles[1].page_number == 1
    _, title_dims, _ = RattaRleX2Decoder().decode(
        titles[0].content or b"", fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT
    )
    assert title_dims == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)

    kw_names = [k.keyword for k in nb.keywords]
    assert kw_names == ["encoder", "cli", "links"]
    assert nb.keywords[2].page_number == 1

    links = nb.links
    web_links = [lk for lk in links if lk.link_type == fileformat.Link.TYPE_WEB_LINK]
    page_links = [lk for lk in links if lk.link_type == fileformat.Link.TYPE_PAGE_LINK]
    assert len(web_links) == 1
    assert web_links[0].target == "https://supernote.com"
    assert len(page_links) == 3
    assert page_links[0].page_id == pages[1].page_id
    assert page_links[1].page_id == pages[1].page_id
    assert page_links[2].page_id == pages[0].page_id

    img0 = ImageConverter(nb).convert(0)
    assert img0.size == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)
    pdf_bytes = PdfConverter(nb).convert(-1, enable_link=True, enable_keyword=True)
    assert pdf_bytes.startswith(b"%PDF")
    svg_str = SvgConverter(nb).convert(0)
    assert "<svg" in svg_str


def test_handwriting_mode_and_hidden_layer_toggle_and_overflow() -> None:
    author = NotebookAuthor(equipment="N6", seed=99)
    author.add_markdown(
        "# Algebra Practice\n\nSolve for x: ~~2x = 10~~ 3x + 6 = 21",
        style=RenderStyle.HANDWRITING,
        background=BackgroundStyle.DOTS,
        hidden_layer_markdown="## Solution\n\n- Subtract 6 -> 3x = 15\n- x = 5",
    )
    nb = author.to_notebook()
    assert nb.total_pages == 1
    assert nb.page(0).style == "style_5mm_dots"

    conv = ImageConverter(nb)
    img_default = np.asarray(conv.convert(0))
    img_revealed = np.asarray(
        conv.convert(
            0,
            visibility_overlay=build_visibility_overlay(
                layer1=VisibilityOverlay.VISIBLE
            ),
        )
    )
    mid_y = fileformat.PAGE_HEIGHT // 2
    assert np.array_equal(img_default[:mid_y], img_revealed[:mid_y])
    assert not np.array_equal(img_default[mid_y:], img_revealed[mid_y:])

    # Multi-page hidden_layer_markdown must emit continuation pages instead of dropping cards
    overflow_author = NotebookAuthor(equipment="N6", seed=10)
    overflow_author.add_markdown(
        "# Short Prompt",
        style=RenderStyle.ARCHITECT,
        hidden_layer_markdown="# Card 1\n\n---\n\n# Card 2",
    )
    overflow_nb = overflow_author.to_notebook()
    assert overflow_nb.total_pages == 2


def test_manta_n5_dimensions_explicit_layer_and_horizontal_page() -> None:
    author = NotebookAuthor(equipment="N5", seed=1)
    overlay_img = Image.new(
        "RGBA",
        (fileformat.A5X2_PAGE_HEIGHT, fileformat.A5X2_PAGE_WIDTH),
        (255, 255, 255, 0),
    )
    arr = np.array(overlay_img, dtype=np.uint8)
    arr[100:180, 200:800] = (0, 0, 0, 255)
    overlay_img = Image.fromarray(arr, mode="RGBA")

    author.add_page(
        background=BackgroundStyle.GRID,
        main_image=overlay_img,
        extra_layers={"LAYER2": ExtraLayerSpec(image=overlay_img, visible=True)},
        horizontal=True,
    )
    author.add_markdown("# Overlay Layer", layer="LAYER2", style="architect")
    nb = author.to_notebook()
    assert nb.width == fileformat.A5X2_PAGE_WIDTH
    assert nb.height == fileformat.A5X2_PAGE_HEIGHT
    rendered = ImageConverter(nb).convert(0)
    assert rendered.size == (fileformat.A5X2_PAGE_HEIGHT, fileformat.A5X2_PAGE_WIDTH)

    with pytest.raises(ValueError, match="custom PNG backgrounds are only supported"):
        author.add_page(custom_background=overlay_img, horizontal=True)


def test_from_notebook_preserves_rtr_and_transcodes_legacy_x1_grayscale_losslessly(
    test_data_dir: Path,
) -> None:
    rtr_path = test_data_dir / "philips" / "rtr.note"
    rtr_nb = load_notebook(str(rtr_path))
    orig_text = TextConverter(rtr_nb).convert(0)
    assert orig_text is not None

    author = NotebookAuthor.from_notebook(rtr_nb, seed=5)
    author.add_markdown(
        "# Agent Summary\n\nAppended follow-up notes.", style="stylized"
    )
    reloaded = author.to_notebook()
    assert reloaded.total_pages == rtr_nb.total_pages + 1
    assert TextConverter(reloaded).convert(0) == orig_text

    # Legacy SN_FILE_VER_20220011 notebook contains X1 0x63/0x64 gray pixels (157 & 201)
    legacy_path = test_data_dir / "philips" / "test.note"
    legacy_nb = load_notebook(str(legacy_path))
    before_p0 = np.asarray(ImageConverter(legacy_nb).convert(0))
    before_p1 = np.asarray(ImageConverter(legacy_nb).convert(1))

    legacy_author = NotebookAuthor.from_notebook(legacy_nb, seed=8)
    legacy_author.add_markdown("# Added Page", style="handwriting")
    upgraded = legacy_author.to_notebook()
    assert upgraded.total_pages == legacy_nb.total_pages + 1

    after_p0 = np.asarray(ImageConverter(upgraded).convert(0))
    after_p1 = np.asarray(ImageConverter(upgraded).convert(1))
    assert np.array_equal(before_p0, after_p0)
    assert np.array_equal(before_p1, after_p1)


def test_utf8_keyword_byte_length_and_pure_empty_export() -> None:
    author = NotebookAuthor(seed=3)
    # Exporting an empty author emits a valid 1-page blank note without mutating the builder
    blank_bytes = author.to_bytes()
    assert load(io.BytesIO(blank_bytes)).total_pages == 1

    author.add_markdown("# Café Notes", style="handwriting")
    kw = author.add_keyword(0, "café")
    assert kw.metadata.keyword_len == len("café".encode("utf-8"))
    nb = author.to_notebook()
    assert nb.total_pages == 1
    assert nb.keywords[0].keyword == "café"


def test_author_validation_and_out_of_range_page_links(test_data_dir: Path) -> None:
    with pytest.raises(ValueError, match="equipment must be one of"):
        NotebookAuthor(equipment="UNKNOWN")
    with pytest.raises(ValueError, match="signature must be one of"):
        NotebookAuthor(signature="SN_FILE_VER_20200001")
    with pytest.raises(ValueError, match="file_id must match"):
        NotebookAuthor(file_id="bad<id>")

    author = NotebookAuthor()
    author.add_page(page_id="P20260101000000000000abcdef123456")
    with pytest.raises(ValueError, match="Duplicate page_id"):
        author.add_page(page_id="P20260101000000000000abcdef123456")
    with pytest.raises(ValueError, match="keyword cannot contain"):
        author.add_keyword(0, "bad>tag")
    with pytest.raises(ValueError, match="conflicts with hidden_layer_name"):
        author.add_markdown(
            "Body",
            layer="LAYER1",
            hidden_layer_markdown="Hidden",
            hidden_layer_name="LAYER1",
        )
    with pytest.raises(ValueError, match="Invalid page link target"):
        author.add_markdown("[Zero](page:0)")

    broken_links = NotebookAuthor()
    broken_links.add_markdown("# Broken\n\nJump to [Missing](page:9)")
    with pytest.raises(ValueError, match="resolves to out-of-range page 9"):
        broken_links.to_bytes()

    partial_nb = load_notebook(
        str(test_data_dir / "20251207_221454.note"), page_number=0
    )
    with pytest.raises(ValueError, match="partially loaded Notebook"):
        NotebookAuthor.from_notebook(partial_nb)

    legacy_nb = load_notebook(str(test_data_dir / "philips" / "test.note"))
    with pytest.raises(ValueError, match="not supported for reconstruction"):
        NotebookAuthor.from_notebook(legacy_nb, upgrade_signature=False)


def test_create_notebook_one_shot(tmp_path: Path) -> None:
    raw = create_notebook(
        "# Quick Note\n\nHello world!", style="handwriting", background="grid"
    )
    nb = load(io.BytesIO(raw))
    assert nb.total_pages == 1

    blank_raw = create_notebook("", background="dots")
    assert load(io.BytesIO(blank_raw)).total_pages == 1

    saved_path = NotebookAuthor().save(tmp_path / "nested" / "saved.note")
    assert saved_path.is_file()
