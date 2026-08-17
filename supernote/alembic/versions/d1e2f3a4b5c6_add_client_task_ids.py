"""add client_task_id and client_task_list_id columns to schedule tables

Revision ID: d1e2f3a4b5c6
Revises: b8e9c0d1e2f3
Create Date: 2026-08-17 00:47:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "b8e9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("t_schedule_task_group") as batch_op:
        batch_op.add_column(
            sa.Column("client_task_list_id", sa.String(), nullable=True)
        )
        batch_op.create_index(
            "ix_t_schedule_task_group_client_task_list_id", ["client_task_list_id"]
        )

    with op.batch_alter_table("t_schedule_task") as batch_op:
        batch_op.add_column(sa.Column("client_task_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("client_task_list_id", sa.String(), nullable=True)
        )
        batch_op.create_index("ix_t_schedule_task_client_task_id", ["client_task_id"])
        batch_op.create_index(
            "ix_t_schedule_task_client_task_list_id", ["client_task_list_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("t_schedule_task") as batch_op:
        batch_op.drop_index("ix_t_schedule_task_client_task_list_id")
        batch_op.drop_index("ix_t_schedule_task_client_task_id")
        batch_op.drop_column("client_task_list_id")
        batch_op.drop_column("client_task_id")

    with op.batch_alter_table("t_schedule_task_group") as batch_op:
        batch_op.drop_index("ix_t_schedule_task_group_client_task_list_id")
        batch_op.drop_column("client_task_list_id")
