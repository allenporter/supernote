"""Add per-user LLM wiki tables (`f_wiki_*`).

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-11-24 04:16:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the seven multi-user `f_wiki_*` tables and tenant-scoped indexes."""
    op.create_table(
        "f_wiki_page",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=191), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("page_kind", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.JSON(), nullable=False),
        sa.Column("edit_policy", sa.String(length=32), nullable=False),
        sa.Column("last_author_kind", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "page_id"),
        sa.UniqueConstraint("user_id", "slug", name="uq_f_wiki_page_user_slug"),
    )
    op.create_index(
        "ix_f_wiki_page_user_kind_updated",
        "f_wiki_page",
        ["user_id", "page_kind", "update_time"],
        unique=False,
    )

    op.create_table(
        "f_wiki_revision",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.JSON(), nullable=False),
        sa.Column("author_kind", sa.String(length=32), nullable=False),
        sa.Column("author_ref", sa.String(length=128), nullable=True),
        sa.Column("change_summary", sa.String(length=512), nullable=False),
        sa.Column("source_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "revision_id"),
        sa.UniqueConstraint(
            "user_id", "page_id", "revision_no", name="uq_f_wiki_revision_page_rev"
        ),
    )
    op.create_index(
        "ix_f_wiki_revision_user_event",
        "f_wiki_revision",
        ["user_id", "source_event_seq"],
        unique=False,
    )

    op.create_table(
        "f_wiki_alias",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("alias_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("alias_text", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "alias_id"),
        sa.UniqueConstraint(
            "user_id", "normalized_alias", name="uq_f_wiki_alias_user_norm"
        ),
    )
    op.create_index(
        "ix_f_wiki_alias_user_page",
        "f_wiki_alias",
        ["user_id", "page_id"],
        unique=False,
    )

    op.create_table(
        "f_wiki_link",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("from_page_id", sa.BigInteger(), nullable=False),
        sa.Column("target_slug", sa.String(length=191), nullable=False),
        sa.Column("target_page_id", sa.BigInteger(), nullable=True),
        sa.Column("link_label", sa.String(length=255), nullable=True),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "from_page_id", "target_slug"),
    )
    op.create_index(
        "ix_f_wiki_link_user_target",
        "f_wiki_link",
        ["user_id", "target_slug"],
        unique=False,
    )
    op.create_index(
        "ix_f_wiki_link_user_target_page",
        "f_wiki_link",
        ["user_id", "target_page_id"],
        unique=False,
    )

    op.create_table(
        "f_wiki_source_ref",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=191), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=True),
        sa.Column("last_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("is_source_deleted", sa.Boolean(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "page_id", "source_type", "source_key"),
    )
    op.create_index(
        "ix_f_wiki_source_ref_user_entity",
        "f_wiki_source_ref",
        ["user_id", "source_type", "source_key"],
        unique=False,
    )
    op.create_index(
        "ix_f_wiki_source_ref_user_file",
        "f_wiki_source_ref",
        ["user_id", "file_id"],
        unique=False,
    )

    op.create_table(
        "f_wiki_checkpoint",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_sync_token", sa.String(length=128), nullable=True),
        sa.Column("pending_events_since_lint", sa.Integer(), nullable=False),
        sa.Column("last_lint_time", sa.BigInteger(), nullable=True),
        sa.Column("backfill_file_cursor", sa.BigInteger(), nullable=True),
        sa.Column("tokens_used_day", sa.Integer(), nullable=False),
        sa.Column("budget_day_utc", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "f_wiki_lint_issue",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("dedup_key", sa.String(length=191), nullable=False),
        sa.Column("issue_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=True),
        sa.Column("target_page_id", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("proposal_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "issue_id"),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_f_wiki_lint_user_dedup"),
    )
    op.create_index(
        "ix_f_wiki_lint_user_status",
        "f_wiki_lint_issue",
        ["user_id", "status", "issue_type"],
        unique=False,
    )
    op.create_index(
        "ix_f_wiki_lint_user_page",
        "f_wiki_lint_issue",
        ["user_id", "page_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all `f_wiki_*` tables and indexes."""
    op.drop_index("ix_f_wiki_lint_user_page", table_name="f_wiki_lint_issue")
    op.drop_index("ix_f_wiki_lint_user_status", table_name="f_wiki_lint_issue")
    op.drop_table("f_wiki_lint_issue")

    op.drop_table("f_wiki_checkpoint")

    op.drop_index("ix_f_wiki_source_ref_user_file", table_name="f_wiki_source_ref")
    op.drop_index("ix_f_wiki_source_ref_user_entity", table_name="f_wiki_source_ref")
    op.drop_table("f_wiki_source_ref")

    op.drop_index("ix_f_wiki_link_user_target_page", table_name="f_wiki_link")
    op.drop_index("ix_f_wiki_link_user_target", table_name="f_wiki_link")
    op.drop_table("f_wiki_link")

    op.drop_index("ix_f_wiki_alias_user_page", table_name="f_wiki_alias")
    op.drop_table("f_wiki_alias")

    op.drop_index("ix_f_wiki_revision_user_event", table_name="f_wiki_revision")
    op.drop_table("f_wiki_revision")

    op.drop_index("ix_f_wiki_page_user_kind_updated", table_name="f_wiki_page")
    op.drop_table("f_wiki_page")
