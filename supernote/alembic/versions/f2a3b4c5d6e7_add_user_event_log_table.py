"""add user event log table

Revision ID: f2a3b4c5d6e7
Revises: e6f7a8b9c0d1
Create Date: 2026-11-09 06:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create `f_user_event` append-only domain event log table and indexes."""
    op.create_table(
        "f_user_event",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("related_file_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "seq"),
    )
    op.create_index(
        "ix_f_user_event_user_file_seq",
        "f_user_event",
        ["user_id", "related_file_id", "seq"],
        unique=False,
    )
    op.create_index(
        "ix_f_user_event_ts",
        "f_user_event",
        ["timestamp_ms"],
        unique=False,
    )


def downgrade() -> None:
    """Drop `f_user_event` table and indexes."""
    op.drop_index("ix_f_user_event_ts", table_name="f_user_event")
    op.drop_index("ix_f_user_event_user_file_seq", table_name="f_user_event")
    op.drop_table("f_user_event")
