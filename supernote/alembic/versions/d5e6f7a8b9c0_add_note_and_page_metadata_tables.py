"""add f_note_metadata and f_note_page_metadata tables

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-11-02 04:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "f_note_metadata",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("native_file_id", sa.String(), nullable=True),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("equipment", sa.String(), nullable=True),
        sa.Column("signature", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("recogn_language", sa.String(), nullable=True),
        sa.Column("is_realtime_recognition", sa.Boolean(), nullable=False),
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
        sa.Column("page_style", sa.String(), nullable=True),
        sa.Column("style_hash", sa.String(), nullable=True),
        sa.Column("orientation", sa.String(), nullable=False),
        sa.Column("recogn_status", sa.Integer(), nullable=False),
        sa.Column("has_ink", sa.Boolean(), nullable=False),
        sa.Column("has_drawables", sa.Boolean(), nullable=False),
        sa.Column("has_textbox", sa.Boolean(), nullable=False),
        sa.Column("has_vector_graph", sa.Boolean(), nullable=False),
        sa.Column("has_content", sa.Boolean(), nullable=False),
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
