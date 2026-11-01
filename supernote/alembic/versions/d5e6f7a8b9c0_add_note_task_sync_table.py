"""add f_note_task_sync table for handwritten task extraction

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-10-26 05:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create f_note_task_sync table."""
    op.create_table(
        "f_note_task_sync",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("page_index", sa.BigInteger(), nullable=False),
        sa.Column("normalized_title", sa.String(), nullable=False),
        sa.Column("raw_title", sa.String(), nullable=False),
        sa.Column("schedule_task_id", sa.String(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=False),
        sa.Column("last_ocr_state", sa.String(), nullable=False),
        sa.Column("last_detail", sa.Text(), nullable=True),
        sa.Column("last_importance", sa.String(), nullable=True),
        sa.Column("last_due_time", sa.BigInteger(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", "user_id"),
        sa.UniqueConstraint(
            "user_id",
            "file_id",
            "page_id",
            "normalized_title",
            name="uq_note_task_sync",
        ),
    )
    op.create_index(
        op.f("ix_f_note_task_sync_user_id"),
        "f_note_task_sync",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_note_task_sync_file_id"),
        "f_note_task_sync",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_note_task_sync_schedule_task_id"),
        "f_note_task_sync",
        ["schedule_task_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop f_note_task_sync table."""
    op.drop_index(
        op.f("ix_f_note_task_sync_schedule_task_id"),
        table_name="f_note_task_sync",
    )
    op.drop_index(
        op.f("ix_f_note_task_sync_file_id"),
        table_name="f_note_task_sync",
    )
    op.drop_index(
        op.f("ix_f_note_task_sync_user_id"),
        table_name="f_note_task_sync",
    )
    op.drop_table("f_note_task_sync")
