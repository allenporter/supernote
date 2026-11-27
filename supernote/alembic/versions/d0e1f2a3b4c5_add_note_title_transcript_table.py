"""add f_note_title_transcript table and drop f_note_title.text_content

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-26 19:52:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "f_note_title_transcript",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("bitmap_md5", sa.String(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "file_id", "bitmap_md5"),
    )
    op.create_index(
        op.f("ix_f_note_title_transcript_file_id"),
        "f_note_title_transcript",
        ["file_id"],
        unique=False,
    )
    with op.batch_alter_table("f_note_title") as batch_op:
        batch_op.drop_column("text_content")


def downgrade() -> None:
    with op.batch_alter_table("f_note_title") as batch_op:
        batch_op.add_column(sa.Column("text_content", sa.Text(), nullable=True))
    op.drop_index(
        op.f("ix_f_note_title_transcript_file_id"),
        table_name="f_note_title_transcript",
    )
    op.drop_table("f_note_title_transcript")
