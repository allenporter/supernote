"""Add entity_type and rename file_id to entity_id on f_system_task

Revision ID: f3c4d5e6f7a8
Revises: e1f2a3b4c5d6
Create Date: 2026-11-27 22:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    """Add entity_type (default 'file') and rename file_id to entity_id on f_system_task."""
    op.drop_index(op.f("ix_f_system_task_file_id"), table_name="f_system_task")

    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_system_task", type_="unique")
        batch_op.alter_column(
            "file_id",
            new_column_name="entity_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "entity_type",
                sa.String(),
                nullable=False,
                server_default="file",
            )
        )

    # Recreate uq_system_task in a second batch block because SQLite batch_alter_table
    # cannot reference a column renamed within the same block when building constraints.
    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.create_unique_constraint(
            "uq_system_task",
            ["user_id", "entity_type", "entity_id", "task_type", "key"],
        )

    op.create_index(
        op.f("ix_f_system_task_entity_type"),
        "f_system_task",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_f_system_task_entity_id"),
        "f_system_task",
        ["entity_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove entity_type and rename entity_id back to file_id on f_system_task."""
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM f_system_task WHERE entity_type != 'file'"))

    op.drop_index(op.f("ix_f_system_task_entity_id"), table_name="f_system_task")
    op.drop_index(op.f("ix_f_system_task_entity_type"), table_name="f_system_task")

    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_system_task", type_="unique")
        batch_op.drop_column("entity_type")
        batch_op.alter_column(
            "entity_id",
            new_column_name="file_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )

    with op.batch_alter_table(
        "f_system_task", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.create_unique_constraint(
            "uq_system_task", ["user_id", "file_id", "task_type", "key"]
        )

    op.create_index(
        op.f("ix_f_system_task_file_id"),
        "f_system_task",
        ["file_id"],
        unique=False,
    )
