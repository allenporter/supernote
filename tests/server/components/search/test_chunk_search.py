"""Unit tests for pure scoring helpers in `supernote.server.components.search.chunk_search`."""

from __future__ import annotations

import numpy as np

from supernote.server.components.search.chunk_search import (
    _EmbeddingRow,
    _score_embedding_rows,
)


def test_score_embedding_rows_clamps_cosine_and_breaks_ties_deterministically() -> None:
    query_unit = np.array([1.0, 0.0, 0.0], dtype=float)
    rows = [
        _EmbeddingRow(3, 20, "B.note", 1, "p1", None, "[1.0, 0.0, 0.0]"),
        _EmbeddingRow(2, 10, "A.note", 2, "p2", None, "[1.0, 0.0, 0.0]"),
        _EmbeddingRow(1, 10, "A.note", 0, "p0", None, "[1.0, 0.0, 0.0]"),
    ]
    scored = _score_embedding_rows(query_unit, rows)
    assert [(r.file_id, r.page_index, score) for r, score in scored] == [
        (10, 0, 1.0),
        (10, 2, 1.0),
        (20, 1, 1.0),
    ]
