"""Tests for `supernote.server.components.wiki.export` (`WikiExportService`)."""

from __future__ import annotations

import io
import zipfile

import pytest
import yaml

from supernote.models.wiki import WikiSourceType
from supernote.server.components.wiki.export import WikiExportService
from supernote.server.components.wiki.models import (
    WikiNotFoundError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from supernote.server.components.wiki.service import WikiService
from supernote.server.db.session import DatabaseSessionManager


async def test_export_empty_vault_zip(
    session_manager: DatabaseSessionManager,
) -> None:
    exporter = WikiExportService(WikiService(session_manager))
    raw_zip = await exporter.export_vault_zip(1)
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        assert zf.namelist() == []


async def test_export_page_and_vault_zip_round_trip(
    session_manager: DatabaseSessionManager,
) -> None:
    wiki = WikiService(session_manager)
    exporter = WikiExportService(wiki)

    await wiki.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/alpha",
            title="Alpha",
            page_kind="project",
            body_md="# Alpha\n\nLinked to [[entities/alice]].",
            aliases=["Proj Alpha"],
            source_refs=[
                WikiSourceRefDTO(
                    source_type=WikiSourceType.NOTE_PAGE, source_key="7:p1", file_id=7
                )
            ],
            author_kind="compiler",
        ),
    )
    await wiki.upsert_page(
        2,
        WikiUpsertInput(
            slug="projects/other-user",
            title="Secret",
            body_md="Should not leak to user 1.",
            author_kind="compiler",
        ),
    )

    md = await exporter.export_page_markdown(1, "projects/alpha")
    parts = md.split("---\n")
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["slug"] == "projects/alpha"
    assert frontmatter["aliases"] == ["Proj Alpha"]
    assert frontmatter["sources"] == ["note_page:7:p1"]
    assert "[[entities/alice]]" in parts[2]

    with pytest.raises(WikiNotFoundError):
        await exporter.export_page_markdown(1, "projects/other-user")

    raw_zip = await exporter.export_vault_zip(1)
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        assert zf.namelist() == ["projects/alpha.md"]
        assert zf.read("projects/alpha.md").decode("utf-8") == md
