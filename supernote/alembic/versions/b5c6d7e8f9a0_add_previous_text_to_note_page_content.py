"""Add previous_text column to f_note_page_content

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-23 05:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable previous_text column to f_note_page_content."""
    op.add_column(
        "f_note_page_content",
        sa.Column("previous_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop previous_text column from f_note_page_content."""
    op.drop_column("f_note_page_content", "previous_text")
