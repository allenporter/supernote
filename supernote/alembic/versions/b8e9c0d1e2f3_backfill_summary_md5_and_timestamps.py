"""backfill summary md5 and timestamps

Revision ID: b8e9c0d1e2f3
Revises: 7a8291f043bc
Create Date: 2026-08-09 15:30:00.000000

"""

import hashlib
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e9c0d1e2f3"
down_revision: Union[str, None] = "7a8291f043bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()
    logger.info(
        "Starting summary MD5 and timestamp backfill migration (b8e9c0d1e2f3)..."
    )

    # 1. Backfill creation_time with create_time if NULL
    res_creation = bind.execute(
        sa.text(
            "UPDATE f_summary SET creation_time = create_time WHERE creation_time IS NULL AND create_time IS NOT NULL"
        )
    )
    creation_updated = res_creation.rowcount if hasattr(res_creation, "rowcount") else 0
    logger.info("Backfilled creation_time for %d summaries", creation_updated)

    # 2. Backfill last_modified_time with update_time or create_time if NULL
    res_modified = bind.execute(
        sa.text(
            "UPDATE f_summary SET last_modified_time = COALESCE(update_time, create_time) WHERE last_modified_time IS NULL"
        )
    )
    modified_updated = res_modified.rowcount if hasattr(res_modified, "rowcount") else 0
    logger.info("Backfilled last_modified_time for %d summaries", modified_updated)

    # 3. Backfill md5_hash from content if NULL
    result = bind.execute(
        sa.text(
            "SELECT id, content FROM f_summary WHERE md5_hash IS NULL AND content IS NOT NULL"
        )
    )
    rows = result.fetchall()
    logger.info("Found %d summaries needing md5_hash calculation", len(rows))

    md5_updated = 0
    md5_skipped = 0
    for row in rows:
        summary_id, content = row[0], row[1]
        if content:
            try:
                md5_hex = hashlib.md5(content.encode("utf-8")).hexdigest()
                bind.execute(
                    sa.text("UPDATE f_summary SET md5_hash = :md5 WHERE id = :id"),
                    {"md5": md5_hex, "id": summary_id},
                )
                md5_updated += 1
            except Exception as exc:
                logger.warning(
                    "Failed to compute MD5 hash for summary ID %s: %s",
                    summary_id,
                    exc,
                )
                md5_skipped += 1

    logger.info(
        "Completed summary backfill migration (b8e9c0d1e2f3): creation_time backfilled=%d, last_modified_time backfilled=%d, md5_hash updated=%d, md5_hash skipped=%d",
        creation_updated,
        modified_updated,
        md5_updated,
        md5_skipped,
    )


def downgrade() -> None:
    # Data backfill migrations are non-destructive and do not require schema rollback
    pass
