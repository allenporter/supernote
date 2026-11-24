"""Unit tests for `supernote.server.components.search.models`."""

from __future__ import annotations

from supernote.server.components.search.models import NotebookInfo, SearchResult


def test_search_result_defaults_date_to_none() -> None:
    hit = SearchResult(
        file_id=10,
        file_name="Lab.note",
        page_index=2,
        page_id="P20260401090000a",
        score=0.92,
        text_preview="[#optics] Bench alignment",
    )
    assert hit.date is None


def test_notebook_info_preserves_timestamps() -> None:
    info = NotebookInfo(
        file_id=11,
        file_name="Daily.note",
        create_time=1000,
        update_time=2000,
    )
    assert (info.file_id, info.file_name, info.create_time, info.update_time) == (
        11,
        "Daily.note",
        1000,
        2000,
    )
