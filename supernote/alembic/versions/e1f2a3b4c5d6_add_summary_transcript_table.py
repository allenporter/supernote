"""add f_summary_transcript table

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-27 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "f_summary_transcript",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_id", sa.BigInteger(), nullable=False),
        sa.Column("handwrite_md5", sa.String(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "summary_id"),
    )
    op.create_index(
        op.f("ix_f_summary_transcript_summary_id"),
        "f_summary_transcript",
        ["summary_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_f_summary_transcript_summary_id"),
        table_name="f_summary_transcript",
    )
    op.drop_table("f_summary_transcript")
