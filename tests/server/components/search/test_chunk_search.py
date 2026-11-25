"""Unit tests for pure hybrid ranking math in `supernote.server.components.search.chunk_search`."""

from __future__ import annotations

import pytest

from supernote.server.components.search.chunk_search import rank_and_merge_results
from supernote.server.components.search.models import SearchResult


def test_rank_and_merge_results_fuses_scores_and_drops_below_floor_noise() -> None:
    kw_hits = [
        SearchResult(1, "Neg.note", 0, "p_neg", 1.0, "Keywords: #optics"),
        SearchResult(2, "Hybrid.note", 0, "p_hyb", 0.92, "[#optics] Mirror grinding"),
        SearchResult(2, "Hybrid.note", 0, "p_hyb", 0.75, "Lower duplicate hit"),
        SearchResult(
            3, "Header.note", 0, "p_hdr", 0.85, "Keywords: optics, lasers in header"
        ),
    ]
    vec_hits = [
        SearchResult(1, "Neg.note", 0, "p_neg", -0.4, "Unrelated grocery list"),
        SearchResult(2, "Hybrid.note", 0, "p_hyb", 0.70, "Mirror grinding"),
        SearchResult(3, "Header.note", 0, "p_hdr", 0.60, "Later paragraph snippet"),
        SearchResult(4, "Noise.note", 0, "p_noise", 0.05, "Low cosine noise"),
        SearchResult(5, "Semantic.note", 0, "p_sem", 0.55, "Parabolic lens notes"),
    ]

    merged = rank_and_merge_results(kw_hits, vec_hits, top_n=10)
    assert len(merged) == 4
    assert merged[1].score == pytest.approx(0.92 + 0.5 * 0.70 * 0.08)
    assert merged[2].score == pytest.approx(0.85 + 0.5 * 0.60 * 0.15)
    assert merged == [
        SearchResult(1, "Neg.note", 0, "p_neg", 1.0, "Keywords: #optics"),
        SearchResult(
            2, "Hybrid.note", 0, "p_hyb", merged[1].score, "[#optics] Mirror grinding"
        ),
        SearchResult(
            3,
            "Header.note",
            0,
            "p_hdr",
            merged[2].score,
            "Keywords: optics, lasers in header",
        ),
        SearchResult(5, "Semantic.note", 0, "p_sem", 0.55, "Parabolic lens notes"),
    ]
    assert rank_and_merge_results(kw_hits, vec_hits, top_n=0) == []
