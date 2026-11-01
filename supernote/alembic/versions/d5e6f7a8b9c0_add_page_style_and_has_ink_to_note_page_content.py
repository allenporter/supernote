"""add page_style and has_ink to note page content

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-11-01 05:05:00.000000

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
    with op.batch_alter_table("f_note_page_content") as batch_op:
        batch_op.add_column(sa.Column("page_style", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("has_ink", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("f_note_page_content") as batch_op:
        batch_op.drop_column("has_ink")
        batch_op.drop_column("page_style")
