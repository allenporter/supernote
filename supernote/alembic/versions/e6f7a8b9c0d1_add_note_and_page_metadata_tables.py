"""add f_note_metadata and f_note_page_metadata tables

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-08 05:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "f_note_metadata",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("native_file_id", sa.String(), nullable=True),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("signature", sa.String(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("header_json", sa.Text(), nullable=False),
        sa.Column("footer_json", sa.Text(), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "file_id"),
    )
    op.create_index(
        op.f("ix_f_note_metadata_file_id"),
        "f_note_metadata",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_f_note_metadata_user_native_file_id",
        "f_note_metadata",
        ["user_id", "native_file_id"],
        unique=False,
    )

    op.create_table(
        "f_note_page_metadata",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("page_style", sa.String(), nullable=True),
        sa.Column("has_ink", sa.Boolean(), nullable=False),
        sa.Column("has_drawables", sa.Boolean(), nullable=False),
        sa.Column("page_json", sa.Text(), nullable=False),
        sa.Column("keywords_json", sa.Text(), nullable=False),
        sa.Column("titles_json", sa.Text(), nullable=False),
        sa.Column("links_json", sa.Text(), nullable=False),
        sa.Column("create_time", sa.BigInteger(), nullable=False),
        sa.Column("update_time", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "file_id", "page_index"),
    )
    op.create_index(
        op.f("ix_f_note_page_metadata_file_id"),
        "f_note_page_metadata",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_f_note_page_metadata_user_file_page_id",
        "f_note_page_metadata",
        ["user_id", "file_id", "page_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_f_note_page_metadata_user_file_page_id",
        table_name="f_note_page_metadata",
    )
    op.drop_index(
        op.f("ix_f_note_page_metadata_file_id"),
        table_name="f_note_page_metadata",
    )
    op.drop_table("f_note_page_metadata")

    op.drop_index(
        "ix_f_note_metadata_user_native_file_id",
        table_name="f_note_metadata",
    )
    op.drop_index(
        op.f("ix_f_note_metadata_file_id"),
        table_name="f_note_metadata",
    )
    op.drop_table("f_note_metadata")
