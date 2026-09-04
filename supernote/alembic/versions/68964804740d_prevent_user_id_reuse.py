"""Prevent reuse of deleted SQLite user IDs.

Revision ID: 68964804740d
Revises: d1e2f3a4b5c6
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "68964804740d"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    # Old deletions may have left owner rows behind. Preserve their highest user
    # ID as part of the sequence floor so none can become visible after upgrade.
    tables = (
        "users",
        "devices",
        "login_records",
        "f_user_file",
        "f_capacity",
        "f_recycle_file",
        "f_summary",
        "f_summary_tag",
        "t_schedule_task",
        "t_schedule_task_group",
    )

    def max_owner_id(table: str) -> int:
        column = "id" if table == "users" else "user_id"
        query = text(f'SELECT COALESCE(MAX({column}), 0) FROM "{table}"')
        return int(bind.execute(query).scalar_one())

    floor = max(max_owner_id(table) for table in tables)

    with op.batch_alter_table(
        "users", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ):
        pass

    current = int(
        bind.execute(
            text(
                "SELECT COALESCE(MAX(seq), 0) FROM sqlite_sequence "
                "WHERE name = 'users'"
            )
        ).scalar_one()
    )
    sequence = max(floor, current)
    result = bind.execute(
        text("UPDATE sqlite_sequence SET seq = :seq WHERE name = 'users'"),
        {"seq": sequence},
    )
    if result.rowcount == 0:
        bind.execute(
            text("INSERT INTO sqlite_sequence(name, seq) VALUES ('users', :seq)"),
            {"seq": sequence},
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("users", recreate="always"):
        pass
