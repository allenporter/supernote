"""Unit tests for LLM Wiki ORM models (`f_wiki_*`)."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.wiki import (
    WikiAliasDO,
    WikiCheckpointDO,
    WikiLinkDO,
    WikiLintIssueDO,
    WikiPageDO,
    WikiRevisionDO,
    WikiSourceRefDO,
)


async def test_wiki_page_and_revision_defaults(db_session: AsyncSession) -> None:
    """Verify CRUD and defaults for `WikiPageDO` and `WikiRevisionDO`."""
    page = WikiPageDO(
        user_id=1,
        slug="projects/q3-roadmap",
        title="Q3 Roadmap",
        body_md="# Q3 Roadmap\n\nSee [[entities/alice]].",
        claims_json=[
            {"claim_id": "c1", "text": "Launch in October", "status": "active"}
        ],
    )
    db_session.add(page)
    await db_session.flush()

    rev = WikiRevisionDO(
        user_id=1,
        page_id=page.page_id,
        revision_no=1,
        title=page.title,
        body_md=page.body_md,
        author_kind="compiler",
    )
    db_session.add(rev)
    await db_session.commit()

    fetched_page = (
        await db_session.execute(
            select(WikiPageDO).where(
                WikiPageDO.user_id == 1, WikiPageDO.slug == "projects/q3-roadmap"
            )
        )
    ).scalar_one()
    assert fetched_page.page_kind == "topic"
    assert fetched_page.summary == ""
    assert fetched_page.version == 1
    assert fetched_page.edit_policy == "auto"
    assert fetched_page.last_author_kind == "compiler"
    assert fetched_page.is_deleted is False

    fetched_rev = (
        await db_session.execute(
            select(WikiRevisionDO).where(
                WikiRevisionDO.user_id == 1,
                WikiRevisionDO.page_id == page.page_id,
                WikiRevisionDO.revision_no == 1,
            )
        )
    ).scalar_one()
    assert fetched_rev.claims_json == []
    assert fetched_rev.author_ref is None
    assert fetched_rev.change_summary == ""
    assert fetched_rev.source_event_seq is None


async def test_wiki_graph_and_provenance_defaults(db_session: AsyncSession) -> None:
    """Verify CRUD and defaults for `WikiAliasDO`, `WikiLinkDO`, and `WikiSourceRefDO`."""
    db_session.add_all(
        [
            WikiAliasDO(
                user_id=1,
                page_id=10,
                alias_text="Q3 Plan",
                normalized_alias="q3 plan",
            ),
            WikiLinkDO(
                user_id=1,
                from_page_id=10,
                target_slug="entities/alice",
            ),
            WikiSourceRefDO(
                user_id=1,
                page_id=10,
                source_type="note_page",
                source_key="42:page_1",
                file_id=42,
            ),
        ]
    )
    await db_session.commit()

    alias = (
        await db_session.execute(select(WikiAliasDO).where(WikiAliasDO.user_id == 1))
    ).scalar_one()
    assert alias.origin == "compiler"

    link = (
        await db_session.execute(select(WikiLinkDO).where(WikiLinkDO.user_id == 1))
    ).scalar_one()
    assert link.target_page_id is None
    assert link.link_label is None

    source_ref = (
        await db_session.execute(
            select(WikiSourceRefDO).where(WikiSourceRefDO.user_id == 1)
        )
    ).scalar_one()
    assert source_ref.is_source_deleted is False
    assert source_ref.last_event_seq is None


async def test_wiki_checkpoint_and_lint_defaults(db_session: AsyncSession) -> None:
    """Verify CRUD and defaults for `WikiCheckpointDO` and `WikiLintIssueDO`."""
    db_session.add_all(
        [
            WikiCheckpointDO(user_id=1, last_sync_token="v1:100"),
            WikiLintIssueDO(
                user_id=1,
                dedup_key="broken_link:10:0:entities/alice",
                issue_type="broken_link",
                page_id=10,
                description="Target page entities/alice does not exist.",
            ),
        ]
    )
    await db_session.commit()

    checkpoint = (
        await db_session.execute(
            select(WikiCheckpointDO).where(WikiCheckpointDO.user_id == 1)
        )
    ).scalar_one()
    assert checkpoint.last_sync_token == "v1:100"
    assert checkpoint.status == "idle"
    assert checkpoint.pending_events_since_lint == 0
    assert checkpoint.tokens_used_day == 0
    assert checkpoint.last_error is None

    issue = (
        await db_session.execute(
            select(WikiLintIssueDO).where(WikiLintIssueDO.user_id == 1)
        )
    ).scalar_one()
    assert issue.status == "open"
    assert issue.severity == "warn"
    assert issue.proposal_json is None


@pytest.mark.parametrize(
    "make_row",
    [
        pytest.param(
            lambda uid: WikiPageDO(user_id=uid, slug="entities/alice", title="Alice"),
            id="uq_f_wiki_page_user_slug",
        ),
        pytest.param(
            lambda uid: WikiRevisionDO(
                user_id=uid,
                page_id=10,
                revision_no=1,
                title="Alice",
                body_md="Body",
                author_kind="compiler",
            ),
            id="uq_f_wiki_revision_page_rev",
        ),
        pytest.param(
            lambda uid: WikiAliasDO(
                user_id=uid,
                page_id=10,
                alias_text="Alice",
                normalized_alias="alice",
            ),
            id="uq_f_wiki_alias_user_norm",
        ),
        pytest.param(
            lambda uid: WikiLintIssueDO(
                user_id=uid,
                dedup_key="orphan:10",
                issue_type="orphan_page",
                description="Orphan",
            ),
            id="uq_f_wiki_lint_user_dedup",
        ),
    ],
)
async def test_wiki_unique_constraints_are_tenant_scoped(
    db_session: AsyncSession, make_row: Callable[[int], Any]
) -> None:
    """Two users may share the same business key, while duplicates within one user fail."""
    db_session.add_all([make_row(1), make_row(2)])
    await db_session.commit()

    db_session.add(make_row(1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
