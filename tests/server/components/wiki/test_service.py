"""Tests for `supernote.server.components.wiki.service` (`WikiService`)."""

from __future__ import annotations

import pytest

from supernote.server.components.wiki.models import (
    WikiConflictError,
    WikiNotFoundError,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from supernote.server.components.wiki.service import WikiService
from supernote.server.db.session import DatabaseSessionManager


async def test_upsert_get_list_revisions_and_backlinks(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)

    project = await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/q3-roadmap",
            title="Q3 Roadmap",
            page_kind="project",
            summary="Quarterly plan",
            body_md="Owner: [[entities/alice|Alice]].",
            aliases=["Q3 Plan", "q3  plan"],
            source_refs=[
                WikiSourceRefDTO(
                    source_type="note_page",
                    source_key="42:p1",
                    file_id=42,
                    last_event_seq=10,
                )
            ],
            author_kind="compiler",
            author_ref="system:wiki",
            change_summary="Initial compile",
        ),
    )
    assert project.version == 1
    assert project.edit_policy == "auto"
    assert project.outbound_links == ["entities/alice"]
    assert project.aliases == ["Q3 Plan"]
    assert len(project.source_refs) == 1

    alice = await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/alice",
            title="Alice",
            page_kind="entity",
            body_md="Leads [[projects/q3-roadmap]].",
            author_kind="compiler",
        ),
    )
    assert alice.backlinks == ["projects/q3-roadmap"]
    assert await service.get_page(2, "projects/q3-roadmap") is None

    listed = await service.list_pages(1, page_kind="project")
    assert [p.slug for p in listed] == ["projects/q3-roadmap"]

    revisions = await service.list_revisions(1, "projects/q3-roadmap")
    assert [r.revision_no for r in revisions] == [1]


@pytest.mark.parametrize("non_user_author", ["compiler", "agent"])
async def test_edit_policy_blocks_non_user_writers(
    session_manager: DatabaseSessionManager, non_user_author: str
) -> None:
    service = WikiService(session_manager)
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="topics/design",
            title="Design",
            body_md="Human prose",
            author_kind="user",
        ),
    )

    with pytest.raises(WikiPolicyError):
        await service.upsert_page(
            1,
            WikiUpsertInput(
                slug="topics/design",
                title="Design",
                body_md="Overwrite attempt",
                author_kind=non_user_author,
            ),
        )


async def test_invalid_author_kind_and_optimistic_conflict(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    with pytest.raises(ValueError, match="author_kind"):
        await service.upsert_page(
            1,
            WikiUpsertInput(
                slug="topics/x", title="X", body_md="B", author_kind="hacker"
            ),
        )

    await service.upsert_page(
        1,
        WikiUpsertInput(slug="topics/x", title="X", body_md="B", author_kind="user"),
    )
    with pytest.raises(WikiConflictError) as exc_info:
        await service.upsert_page(
            1,
            WikiUpsertInput(
                slug="topics/x",
                title="X",
                body_md="Stale",
                author_kind="user",
                expected_version=99,
            ),
        )
    assert exc_info.value.actual == 1


async def test_tombstone_revival_resets_policy_and_clears_stale_source_refs(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    created = await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/bob",
            title="Bob",
            body_md="Initial",
            edit_policy="locked",
            source_refs=[
                WikiSourceRefDTO(source_type="note_page", source_key="1:p1", file_id=1)
            ],
            author_kind="user",
        ),
    )
    await service.delete_page(1, "entities/bob")
    assert await service.get_page(1, "entities/bob") is None

    # expected_version=0 succeeds on tombstone revival, resets policy, and drops old source_refs.
    revived = await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/bob",
            title="Bob Revived",
            body_md="Back again",
            author_kind="compiler",
            expected_version=0,
        ),
    )
    assert revived.page_id == created.page_id
    assert revived.version == 3
    assert revived.edit_policy == "auto"
    assert revived.source_refs == []


async def test_alias_collision_rejected_for_compiler_reassigned_for_user(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/alice",
            title="Alice",
            body_md="A",
            aliases=["Lead"],
            author_kind="compiler",
        ),
    )
    with pytest.raises(WikiPolicyError, match="already owned"):
        await service.upsert_page(
            1,
            WikiUpsertInput(
                slug="entities/bob",
                title="Bob",
                body_md="B",
                aliases=["lead"],
                author_kind="compiler",
            ),
        )
    reassigned = await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/bob",
            title="Bob",
            body_md="B",
            aliases=["Lead"],
            author_kind="user",
        ),
    )
    assert reassigned.aliases == ["Lead"]


async def test_search_structural_lint_self_links_and_cleanup(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/alpha",
            title="Alpha Launch",
            page_kind="project",
            summary="Launch checklist",
            body_md="Self [[projects/alpha]] and missing [[entities/missing]].",
            aliases=["Project A"],
            source_refs=[
                WikiSourceRefDTO(
                    source_type="schedule_task",
                    source_key="task-1",
                    is_source_deleted=True,
                )
            ],
            author_kind="compiler",
        ),
    )

    assert await service.search_pages(1, "   ") == []
    hits = await service.search_pages(1, "project a launch")
    assert len(hits) == 1
    assert hits[0].slug == "projects/alpha"
    assert "entities/missing" in hits[0].neighbor_slugs

    # Self-link must NOT hide orphan_page detection.
    issues = await service.run_structural_lint(1)
    assert {i.issue_type for i in issues} == {
        "broken_link",
        "orphan_page",
        "stale_source",
    }

    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/missing",
            title="Missing",
            body_md="Linked back to [[projects/alpha]].",
            author_kind="compiler",
        ),
    )
    after_fix = await service.run_structural_lint(1)
    assert {i.issue_type for i in after_fix} == {"stale_source"}

    status = await service.get_status(1)
    assert status.page_count == 2
    assert status.open_lint_count == 1

    resolved = await service.resolve_lint_issue(
        1, after_fix[0].issue_id, status="dismissed"
    )
    assert resolved.status == "dismissed"
    with pytest.raises(WikiNotFoundError):
        await service.resolve_lint_issue(1, 999999)

    await service.delete_user_wiki(1)
    assert (await service.get_status(1)).page_count == 0


async def test_sync_index_page_generates_catalog_is_idempotent_and_respects_protection(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    assert await service.sync_index_page(1) is None

    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/aurora",
            title="Aurora Home Server",
            page_kind="project",
            summary="TrueNAS home server",
            body_md="Server details",
            author_kind="compiler",
        ),
    )
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="entities/alice",
            title="Alice",
            page_kind="entity",
            summary="Cloud release lead",
            body_md="Works on [[projects/aurora]]",
            author_kind="compiler",
        ),
    )

    idx1 = await service.sync_index_page(1)
    assert idx1 is not None
    assert idx1.slug == "index"
    assert idx1.version == 1
    assert "## Projects" in idx1.body_md
    assert "- [[projects/aurora]] — TrueNAS home server" in idx1.body_md
    assert "## Entities" in idx1.body_md
    assert "- [[entities/alice]] — Cloud release lead" in idx1.body_md

    # Calling again with no page changes is idempotent (version does not bump).
    idx2 = await service.sync_index_page(1)
    assert idx2 is not None
    assert idx2.version == 1

    # Manual user edit flips index to protected_prose; sync_index_page must not overwrite it.
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="index",
            title="My Custom Index",
            page_kind="index",
            body_md="Hand-crafted index",
            author_kind="user",
        ),
    )
    idx3 = await service.sync_index_page(1)
    assert idx3 is not None
    assert idx3.body_md == "Hand-crafted index"


async def test_index_links_do_not_mask_orphan_pages_and_delete_refreshes_index(
    session_manager: DatabaseSessionManager,
) -> None:
    service = WikiService(session_manager)
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="topics/lonely",
            title="Lonely Topic",
            page_kind="topic",
            body_md="No other content page links here.",
            author_kind="compiler",
        ),
    )
    await service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/beta",
            title="Beta",
            page_kind="project",
            body_md="Standalone project.",
            author_kind="compiler",
        ),
    )
    await service.sync_index_page(1)

    # Inbound links from `index` must not hide genuinely orphaned content pages.
    issues = await service.run_structural_lint(1)
    orphan_descs = [i.description for i in issues if i.issue_type == "orphan_page"]
    assert any("topics/lonely" in d for d in orphan_descs)

    # Deleting a page must immediately refresh the auto-managed `index` so it
    # never retains a broken wikilink to the deleted page.
    await service.delete_page(1, "projects/beta")
    index_after = await service.get_page(1, "index")
    assert index_after is not None
    assert "projects/beta" not in index_after.body_md
    issues_after = await service.run_structural_lint(1)
    assert not any(i.issue_type == "broken_link" for i in issues_after)
