"""Unit tests for `supernote.server.components.search.models`."""

from __future__ import annotations

from supernote.server.components.search.models import (
    NotebookInfo,
    SearchResult,
)


def test_search_result_defaults_and_fields() -> None:
    """Verify SearchResult stores fields and defaults date to None."""
    hit = SearchResult(
        file_id=10,
        file_name="Journal.note",
        page_index=2,
        page_id="P20260101000000",
        score=0.95,
        text_preview="Hello world",
    )
    assert hit.file_id == 10
    assert hit.file_name == "Journal.note"
    assert hit.page_index == 2
    assert hit.page_id == "P20260101000000"
    assert hit.score == 0.95
    assert hit.text_preview == "Hello world"
    assert hit.date is None


def test_notebook_info_fields() -> None:
    """Verify NotebookInfo stores notebook metadata."""
    info = NotebookInfo(
        file_id=42,
        file_name="Notes.note",
        create_time=1000,
        update_time=2000,
    )
    assert info.file_id == 42
    assert info.file_name == "Notes.note"
    assert info.create_time == 1000
    assert info.update_time == 2000
