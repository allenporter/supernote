"""Add device planner task fields

Extends ``t_schedule_task`` so the Supernote device can write its planner tasks into
the store the CLI already shares (see the ADR
``.scratch/zero-banner-sync/assets/02-planner-store-design.md``):

- add ``device_task_id`` (the device's opaque string id) with a UNIQUE index on
  ``(user_id, device_task_id)`` for upsert-by-device-id — NULL for CLI rows, which SQL
  treats as distinct so the constraint binds device rows only;
- make ``task_list_id`` nullable (device tasks are ungrouped);
- add ``links``, ``is_deleted`` (tombstone), ``last_modified`` (device clock), and the
  ``*sort*`` family.

Non-destructive: additive nullable columns (``is_deleted`` backfills False via
server_default) plus a SQLite batch rebuild that copies existing CLI rows.

Revision ID: 9d2f7b3c1a08
Revises: 0543a383957b
Create Date: 2026-07-23 11:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d2f7b3c1a08"
down_revision: Union[str, Sequence[str], None] = "0543a383957b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = [
    ("device_task_id", sa.String()),
    ("links", sa.String()),
    ("last_modified", sa.BigInteger()),
    ("sort", sa.BigInteger()),
    ("sort_completed", sa.BigInteger()),
    ("planer_sort", sa.BigInteger()),
    ("planer_sort_time", sa.BigInteger()),
    ("sort_time", sa.BigInteger()),
    ("all_sort", sa.BigInteger()),
    ("all_sort_completed", sa.BigInteger()),
    ("all_sort_time", sa.BigInteger()),
]


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite has no ALTER COLUMN, so batch mode rebuilds the table (copying rows) to
    # change task_list_id nullability; the added columns and index ride along.
    with op.batch_alter_table("t_schedule_task") as batch_op:
        for name, col_type in _NEW_COLUMNS:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.alter_column(
            "task_list_id", existing_type=sa.BigInteger(), nullable=True
        )
        batch_op.create_index(
            "uq_schedule_task_device_id",
            ["user_id", "device_task_id"],
            unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("t_schedule_task") as batch_op:
        batch_op.drop_index("uq_schedule_task_device_id")
        batch_op.alter_column(
            "task_list_id", existing_type=sa.BigInteger(), nullable=False
        )
        batch_op.drop_column("is_deleted")
        for name, _ in reversed(_NEW_COLUMNS):
            batch_op.drop_column(name)
