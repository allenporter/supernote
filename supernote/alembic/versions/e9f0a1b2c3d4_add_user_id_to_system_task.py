"""Add user_id to f_system_task primary key and unique constraint

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-11-24 04:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    """Add user_id column, backfill from f_user_file, and scope PK and unique constraint."""
    op.add_column(
        "f_system_task",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE f_system_task
            SET user_id = (
                SELECT f_user_file.user_id
                FROM f_user_file
                WHERE f_user_file.id = f_system_task.file_id
            )
            """
        )
    )
    conn.execute(sa.text("DELETE FROM f_system_task WHERE user_id IS NULL"))

    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_constraint("uq_system_task", type_="unique")
        batch_op.create_unique_constraint(
            "uq_system_task", ["user_id", "file_id", "task_type", "key"]
        )
        batch_op.drop_constraint("pk_f_system_task", type_="primary")
        batch_op.create_primary_key("pk_f_system_task", ["user_id", "id"])


def downgrade() -> None:
    """Remove user_id from f_system_task primary key, unique constraint, and schema."""
    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_system_task", type_="unique")
        batch_op.create_unique_constraint(
            "uq_system_task", ["file_id", "task_type", "key"]
        )
        batch_op.drop_constraint("pk_f_system_task", type_="primary")
        batch_op.create_primary_key("pk_f_system_task", ["id"])
        batch_op.drop_column("user_id")
