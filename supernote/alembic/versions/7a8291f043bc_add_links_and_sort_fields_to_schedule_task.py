"""add links and sort fields to schedule task

Revision ID: 7a8291f043bc
Revises: 0543a383957b
Create Date: 2026-08-02 20:08:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a8291f043bc"
down_revision: Union[str, None] = "0543a383957b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("t_schedule_task", sa.Column("links", sa.String(), nullable=True))
    op.add_column("t_schedule_task", sa.Column("sort", sa.BigInteger(), nullable=True))
    op.add_column(
        "t_schedule_task", sa.Column("sort_completed", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "t_schedule_task", sa.Column("planer_sort", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "t_schedule_task", sa.Column("all_sort", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "t_schedule_task",
        sa.Column("all_sort_completed", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "t_schedule_task", sa.Column("sort_time", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "t_schedule_task", sa.Column("planer_sort_time", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "t_schedule_task", sa.Column("all_sort_time", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("t_schedule_task", "all_sort_time")
    op.drop_column("t_schedule_task", "planer_sort_time")
    op.drop_column("t_schedule_task", "sort_time")
    op.drop_column("t_schedule_task", "all_sort_completed")
    op.drop_column("t_schedule_task", "all_sort")
    op.drop_column("t_schedule_task", "planer_sort")
    op.drop_column("t_schedule_task", "sort_completed")
    op.drop_column("t_schedule_task", "sort")
    op.drop_column("t_schedule_task", "links")
