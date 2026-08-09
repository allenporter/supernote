"""backfill summary md5 and timestamps

Revision ID: b8e9c0d1e2f3
Revises: 7a8291f043bc
Create Date: 2026-08-09 15:30:00.000000

"""

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e9c0d1e2f3"
down_revision: Union[str, None] = "7a8291f043bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Backfill creation_time with create_time if NULL
    bind.execute(
        sa.text(
            "UPDATE f_summary SET creation_time = create_time WHERE creation_time IS NULL AND create_time IS NOT NULL"
        )
    )

    # 2. Backfill last_modified_time with update_time or create_time if NULL
    bind.execute(
        sa.text(
            "UPDATE f_summary SET last_modified_time = COALESCE(update_time, create_time) WHERE last_modified_time IS NULL"
        )
    )

    # 3. Backfill md5_hash from content if NULL
    result = bind.execute(
        sa.text(
            "SELECT id, content FROM f_summary WHERE md5_hash IS NULL AND content IS NOT NULL"
        )
    )
    rows = result.fetchall()
    for row in rows:
        summary_id, content = row[0], row[1]
        if content:
            md5_hex = hashlib.md5(content.encode("utf-8")).hexdigest()
            bind.execute(
                sa.text("UPDATE f_summary SET md5_hash = :md5 WHERE id = :id"),
                {"md5": md5_hex, "id": summary_id},
            )


def downgrade() -> None:
    # Data backfill migrations are non-destructive and do not require schema rollback
    pass
