"""Unit tests for `supernote.server.components.summary.chunking`."""

from __future__ import annotations

import json

from supernote.models.summary import METADATA_CHUNKS
from supernote.server.ai.prompts import SummarySegment
from supernote.server.components.summary.chunking import (
    FormattedPage,
    PageChunk,
    compute_chunk_hash,
    format_prior_context,
    merge_chunk_segments,
    normalize_segments,
    parse_cached_chunks,
    partition_pages,
    render_segments_markdown,
)


def _page(idx: int, date: str | None = None, text: str | None = None) -> FormattedPage:
    return FormattedPage(
        page_index=idx,
        page_id=f"p{idx}",
        page_date=date,
        formatted_text=text
        if text is not None
        else f"--- Page {idx + 1} ---\nBody {idx}",
    )


def test_partition_pages_single_shot_when_disabled() -> None:
    pages = [_page(i) for i in range(20)]
    chunks = partition_pages(pages, max_pages_per_chunk=0, max_chars_per_chunk=100)
    assert len(chunks) == 1
    assert len(chunks[0].pages) == 20


def test_partition_pages_respects_page_and_char_limits() -> None:
    pages = [_page(i, date=f"2026-01-{i + 1:02d}") for i in range(10)]
    chunks = partition_pages(pages, max_pages_per_chunk=4, max_chars_per_chunk=10_000)
    assert [len(c.pages) for c in chunks] == [4, 4, 2]

    dense_pages = [_page(i, text="x" * 60) for i in range(5)]
    char_chunks = partition_pages(
        dense_pages, max_pages_per_chunk=10, max_chars_per_chunk=125
    )
    assert [len(c.pages) for c in char_chunks] == [2, 2, 1]


def test_partition_pages_keeps_single_oversized_page() -> None:
    pages = [_page(0, text="x" * 500), _page(1, text="short")]
    chunks = partition_pages(pages, max_pages_per_chunk=5, max_chars_per_chunk=100)
    assert [len(c.pages) for c in chunks] == [1, 1]
    assert chunks[0].pages[0].page_index == 0


def test_partition_pages_prefers_date_boundary_split() -> None:
    # Pages 0-2 are Jan 1, page 3 is Jan 2, page 4 is also Jan 2.
    # With max_pages_per_chunk=4, page 3 should move into chunk 2 with page 4.
    pages = [
        _page(0, date="2026-01-01"),
        _page(1, date="2026-01-01"),
        _page(2, date="2026-01-01"),
        _page(3, date="2026-01-02"),
        _page(4, date="2026-01-02"),
    ]
    chunks = partition_pages(pages, max_pages_per_chunk=4, max_chars_per_chunk=10_000)
    assert [[p.page_index for p in c.pages] for c in chunks] == [[0, 1, 2], [3, 4]]


def test_compute_chunk_hash_changes_on_content_model_or_prior_context() -> None:
    chunk = PageChunk((_page(0), _page(1)))
    base = compute_chunk_hash(
        chunk, model_id="m1", custom_type="daily", prior_context=None
    )
    assert base == compute_chunk_hash(
        chunk, model_id="m1", custom_type="daily", prior_context=None
    )
    assert base != compute_chunk_hash(
        chunk, model_id="m2", custom_type="daily", prior_context=None
    )
    assert base != compute_chunk_hash(
        chunk, model_id="m1", custom_type="weekly", prior_context=None
    )
    assert base != compute_chunk_hash(
        chunk, model_id="m1", custom_type="daily", prior_context="## 2026-01-01\n- prev"
    )


def test_merge_chunk_segments_combines_adjacent_same_date_range() -> None:
    chunk1 = normalize_segments(
        [
            SummarySegment(
                date_range="2026-02-07",
                summary="- Showroom visit",
                extracted_dates=["2026-02-07"],
                page_refs=[8],
            )
        ]
    )
    chunk2 = normalize_segments(
        [
            SummarySegment(
                date_range="2026-02-07",
                summary="- Ordered Lutron dimmer",
                extracted_dates=["2026-02-07"],
                page_refs=[9],
            ),
            SummarySegment(
                date_range="2026-02-11",
                summary="- Solar permit filed",
                extracted_dates=["2026-02-11"],
                page_refs=[10],
            ),
        ]
    )
    merged = merge_chunk_segments([chunk1, chunk2])
    assert len(merged) == 2
    assert merged[0]["date_range"] == "2026-02-07"
    assert merged[0]["page_refs"] == [8, 9]
    assert "Showroom visit" in merged[0]["summary"]
    assert "Ordered Lutron dimmer" in merged[0]["summary"]
    md = render_segments_markdown(merged)
    assert "## 2026-02-07 (Pages 8, 9)" in md
    assert "## 2026-02-11 (Pages 10)" in md


def test_format_prior_context_bounds_length() -> None:
    segs = [
        {"date_range": "2026-01-01", "summary": "A" * 500, "page_refs": [1]},
        {"date_range": "2026-01-02", "summary": "B" * 500, "page_refs": [2]},
        {"date_range": "2026-01-03", "summary": "C" * 500, "page_refs": [3]},
    ]
    ctx = format_prior_context(segs, max_segments=2, max_chars=200)
    assert ctx is not None
    assert "2026-01-01" not in ctx
    assert "2026-01-02" in ctx
    assert len(ctx) <= 200
    assert ctx.endswith("...")


def test_parse_cached_chunks_handles_valid_and_legacy_metadata() -> None:
    assert parse_cached_chunks(None) == {}
    assert parse_cached_chunks("not-json") == {}
    assert parse_cached_chunks(json.dumps({"segments": []})) == {}

    valid = json.dumps(
        {
            METADATA_CHUNKS: [
                {"chunk_hash": "abc123", "segments": [{"date_range": "2026-01-01"}]}
            ]
        }
    )
    parsed = parse_cached_chunks(valid)
    assert parsed == {"abc123": [{"date_range": "2026-01-01"}]}
