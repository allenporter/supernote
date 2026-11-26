"""add backfill_page_cursor to f_wiki_checkpoint

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-26 17:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "f_wiki_checkpoint",
        sa.Column("backfill_page_cursor", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("f_wiki_checkpoint") as batch_op:
        batch_op.drop_column("backfill_page_cursor")
