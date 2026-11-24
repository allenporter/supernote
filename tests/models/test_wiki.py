"""Unit tests for shared wire models in `supernote.models.wiki`."""

from __future__ import annotations

import pytest

from supernote.models.wiki import (
    WikiCompileResponseVO,
    WikiIndexEntryVO,
    WikiIndexResponseVO,
    WikiPageDTO,
    WikiSourceRefDTO,
)


def test_wiki_source_ref_validation() -> None:
    ref = WikiSourceRefDTO.from_dict(
        {"source_type": "note_page", "source_key": "42:p1", "file_id": 42}
    )
    assert ref.source_type == "note_page"
    assert ref.source_key == "42:p1"
    assert ref.file_id == 42
    assert ref.is_source_deleted is False

    for bad in (
        {"source_type": "", "source_key": "1:p1"},
        {"source_type": "note_page", "source_key": "   "},
    ):
        with pytest.raises(ValueError):
            WikiSourceRefDTO.from_dict(bad)


def test_wiki_index_entry_projection_and_compile_vo_roundtrip() -> None:
    page = WikiPageDTO(
        page_id=1,
        slug="projects/alpha",
        title="Alpha",
        page_kind="project",
        summary="Summary",
        body_md="Long markdown body",
        claims=[],
        edit_policy="auto",
        last_author_kind="compiler",
        version=2,
        create_time=100,
        update_time=200,
    )
    index_vo = WikiIndexResponseVO(entries=[WikiIndexEntryVO.from_page(page)])
    d = index_vo.to_dict()
    assert d["success"] is True
    assert d["entries"] == [
        {
            "slug": "projects/alpha",
            "title": "Alpha",
            "page_kind": "project",
            "summary": "Summary",
            "version": 2,
            "update_time": 200,
        }
    ]

    compile_vo = WikiCompileResponseVO(
        mode="incremental",
        events_processed=0,
        pages_updated=0,
        skipped_policy_pages=0,
        lint_issues_open=0,
        status="idle",
    )
    roundtripped = WikiCompileResponseVO.from_dict(compile_vo.to_dict())
    assert roundtripped.events_processed == 0
    assert roundtripped.issues is None
