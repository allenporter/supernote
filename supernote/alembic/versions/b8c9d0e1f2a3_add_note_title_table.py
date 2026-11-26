"""add f_note_title table

Revision ID: b8c9d0e1f2a3
Revises: e9f0a1b2c3d4
Create Date: 2026-11-26 00:10:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "f_note_title",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("title_index", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("rect_left", sa.Integer(), nullable=True),
        sa.Column("rect_top", sa.Integer(), nullable=True),
        sa.Column("rect_width", sa.Integer(), nullable=True),
        sa.Column("rect_height", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("style", sa.String(), nullable=True),
        sa.Column("bitmap_md5", sa.String(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "file_id", "title_index"),
    )
    op.create_index(
        op.f("ix_f_note_title_file_id"),
        "f_note_title",
        ["file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_f_note_title_file_id"), table_name="f_note_title")
    op.drop_table("f_note_title")
