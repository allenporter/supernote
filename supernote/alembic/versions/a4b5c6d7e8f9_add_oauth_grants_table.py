"""add oauth_grants table for MCP OAuth client grants

Revision ID: a4b5c6d7e8f9
Revises: f3b4c5d6e7f8
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the oauth_grants table."""
    op.create_table(
        "oauth_grants",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=2048), nullable=False),
        sa.Column("scopes", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_index(
        op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Drop the oauth_grants table."""
    op.drop_index(op.f("ix_oauth_grants_user_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
