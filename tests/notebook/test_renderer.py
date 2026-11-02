"""Unit tests for supernote.notebook.renderer."""

from __future__ import annotations

import numpy as np
import pytest

from supernote.notebook import fileformat
from supernote.notebook.renderer import (
    BackgroundStyle,
    LinkSpan,
    MarkdownRenderer,
    RenderStyle,
    get_pagestyle_name,
    get_template_line_spacing,
    render_background,
    render_markdown,
    render_overlay_cards,
)


@pytest.mark.parametrize("bg", list(BackgroundStyle))
def test_render_background_and_pagestyle_names(bg: BackgroundStyle) -> None:
    paper = render_background(bg)
    assert paper.mode == "L"
    assert paper.size == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)
    assert get_template_line_spacing(bg) > 0

    portrait = get_pagestyle_name(bg, equipment="N6", horizontal=False)
    horiz_manta = get_pagestyle_name(bg, equipment="N5", horizontal=True)
    assert portrait.startswith("style_")
    assert horiz_manta.startswith("style_h_")
    assert horiz_manta.endswith("_a5x2")


@pytest.mark.parametrize("style", list(RenderStyle))
def test_bullet_journal_grammar_hr_quotes_and_inline_accents(
    style: RenderStyle,
) -> None:
    md = """#### NOV 2026 · COLLECTION 01
# Rapid Log & Habit Tracker

## HABITS

| Ritual | M | T | W |
| --- | --- | --- | --- |
| Read | x | . | o |

***

### Deep Work Principles

> Quiet paper and ==**crisp typography**== elevate focus #craft [Guide](https://example.com)

* - [ ] Ship ==high-res grayscale== encoder #bujo
! - [-] Quiet stationery grids elevate contrast
– Plain en-dash note
- [*] Starred bracket task
- [!] Bang bracket note
- [x] ~~Archive legacy drafts~~
- [>] Migrate soak suite
- [<] Schedule Q1 review
- [o] Studio sync at `14:00`
1. Ordered step one

Plain paragraph with *italic*, **bold**, `code`, and [Next](page:+1).
"""
    pages = render_markdown(md, style=style, background=BackgroundStyle.GRID, seed=7)
    assert len(pages) == 1
    page = pages[0]
    assert page.image.size == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)

    assert [h.level for h in page.headings] == [1, 2, 3]
    assert [k.keyword for k in page.keywords] == ["craft", "bujo"]
    # Quote keyword & link coordinates must be translated into page space, not local strip (0, 0)
    assert page.keywords[0].rect[0] >= 90
    assert page.keywords[0].rect[1] >= 400
    assert len(page.links) == 2
    assert page.links[0].is_web_link is True
    assert page.links[0].rect[1] >= 400
    assert page.links[1].relative_page_offset == 1

    assert "[ ] Ship high-res grayscale encoder #bujo" in page.text
    assert "[>] Migrate soak suite" in page.text
    assert "[<] Schedule Q1 review" in page.text
    assert "– Quiet stationery grids elevate contrast" in page.text
    assert "○ Studio sync at 14:00" in page.text
    assert "1. Ordered step one" in page.text


def test_overlong_unbroken_token_splits_within_page_bounds() -> None:
    huge_url = "https://supernote.example.com/" + ("segment-" * 30) + "end"
    md = f"# URL Wrapping\n\nVisit [{huge_url}]({huge_url}) for full specifications."
    pages = render_markdown(
        md, style=RenderStyle.STYLIZED, background=BackgroundStyle.WHITE
    )
    assert len(pages) == 1
    alpha = np.asarray(pages[0].image)[:, :, 3]
    nonzero_cols = np.where(alpha.max(axis=0) > 0)[0]
    assert int(nonzero_cols.max()) < fileformat.PAGE_WIDTH - 40
    assert len(pages[0].links) >= 2


def test_multi_page_table_repeats_header_on_continuation_page() -> None:
    rows = ["| Metric | Status | Notes |", "| --- | --- | --- |"]
    for i in range(38):
        rows.append(f"| Item {i:02d} | Ready | Verification row {i:02d} |")
    md = "# Large Table\n\n" + "\n".join(rows)

    pages = render_markdown(
        md, style=RenderStyle.HANDWRITING, background=BackgroundStyle.DOTS, seed=4
    )
    assert len(pages) >= 2
    assert "Metric | Status | Notes" in pages[0].text
    # Header row is drawn visually on page 2, but ground-truth text_lines is not duplicated
    assert "Metric | Status | Notes" not in pages[1].text
    assert "Item 37 | Ready | Verification row 37" in pages[-1].text


def test_automatic_overflow_and_explicit_html_pagebreak() -> None:
    long_md = "\n".join(
        f"- Line item number {i} with enough words to render" for i in range(55)
    )
    rendered = render_markdown(long_md, style="handwriting", background="ruled", seed=3)
    assert len(rendered) >= 2
    assert "Line item number 0" in rendered[0].text
    assert "Line item number 54" in rendered[-1].text

    split_md = "First page\n<!-- pagebreak -->\nSecond page"
    split_pages = render_markdown(split_md)
    assert len(split_pages) == 2


def test_overlay_cards_dynamic_expansion_preserves_single_page_card() -> None:
    medium_notes = "## Coaching Notes\n\n" + "\n".join(
        f"- Insight bullet {i}: review spacing and hierarchy carefully."
        for i in range(12)
    )
    cards = render_overlay_cards(medium_notes, style=RenderStyle.ARCHITECT, seed=5)
    assert len(cards) == 1
    assert "Insight bullet 11" in cards[0].text


def test_link_span_parsing_and_renderer_validation() -> None:
    assert LinkSpan("Web", "https://a.example", (0, 0, 10, 10)).is_web_link is True
    assert LinkSpan("P2", "page:2", (0, 0, 10, 10)).target_page_index == 1
    assert LinkSpan("Zero", "page:0", (0, 0, 10, 10)).target_page_index is None
    assert LinkSpan("Prev", "page:-1", (0, 0, 10, 10)).target_page_index is None
    assert LinkSpan("Prev", "page:-1", (0, 0, 10, 10)).relative_page_offset == -1
    assert LinkSpan("Next", "page:+2", (0, 0, 10, 10)).relative_page_offset == 2

    with pytest.raises(ValueError, match="font_size must be positive"):
        MarkdownRenderer(font_size=0)
    with pytest.raises(ValueError, match="page_width and page_height must be positive"):
        MarkdownRenderer(page_width=-10)
