"""change schedule task and group ids to string

Revision ID: c9a8b7c6d5e4
Revises: b8e9c0d1e2f3
Create Date: 2026-08-17 00:22:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a8b7c6d5e4"
down_revision: Union[str, None] = "b8e9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("t_schedule_task_group") as batch_op:
        batch_op.alter_column("task_list_id", type_=sa.String(), existing_type=sa.BigInteger())

    with op.batch_alter_table("t_schedule_task") as batch_op:
        batch_op.alter_column("task_id", type_=sa.String(), existing_type=sa.BigInteger())
        batch_op.alter_column("task_list_id", type_=sa.String(), existing_type=sa.BigInteger())


def downgrade() -> None:
    with op.batch_alter_table("t_schedule_task") as batch_op:
        batch_op.alter_column("task_list_id", type_=sa.BigInteger(), existing_type=sa.String())
        batch_op.alter_column("task_id", type_=sa.BigInteger(), existing_type=sa.String())

    with op.batch_alter_table("t_schedule_task_group") as batch_op:
        batch_op.alter_column("task_list_id", type_=sa.BigInteger(), existing_type=sa.String())
