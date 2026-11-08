"""add f_rapid_log_entry table for structured Rapid Logging extraction and sync

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-08 06:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create f_rapid_log_entry table."""
    op.create_table(
        "f_rapid_log_entry",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("page_index", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("normalized_text", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("task_state", sa.String(), nullable=True),
        sa.Column("is_starred", sa.Boolean(), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("page_date_ms", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("schedule_task_id", sa.String(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", "user_id"),
        sa.UniqueConstraint(
            "user_id",
            "file_id",
            "page_id",
            "kind",
            "normalized_text",
            name="uq_rapid_log_entry",
        ),
    )
    op.create_index(
        op.f("ix_f_rapid_log_entry_user_id"),
        "f_rapid_log_entry",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_rapid_log_entry_file_id"),
        "f_rapid_log_entry",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_rapid_log_entry_kind"),
        "f_rapid_log_entry",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_rapid_log_entry_page_date_ms"),
        "f_rapid_log_entry",
        ["page_date_ms"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_rapid_log_entry_schedule_task_id"),
        "f_rapid_log_entry",
        ["schedule_task_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop f_rapid_log_entry table."""
    op.drop_index(
        op.f("ix_f_rapid_log_entry_schedule_task_id"),
        table_name="f_rapid_log_entry",
    )
    op.drop_index(
        op.f("ix_f_rapid_log_entry_page_date_ms"),
        table_name="f_rapid_log_entry",
    )
    op.drop_index(
        op.f("ix_f_rapid_log_entry_kind"),
        table_name="f_rapid_log_entry",
    )
    op.drop_index(
        op.f("ix_f_rapid_log_entry_file_id"),
        table_name="f_rapid_log_entry",
    )
    op.drop_index(
        op.f("ix_f_rapid_log_entry_user_id"),
        table_name="f_rapid_log_entry",
    )
    op.drop_table("f_rapid_log_entry")
