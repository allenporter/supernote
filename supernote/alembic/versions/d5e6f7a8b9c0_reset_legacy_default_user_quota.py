"""reset legacy default user quota placeholder to unlimited

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-11-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_DEFAULT_QUOTA_STR = "10737418240"


def upgrade() -> None:
    """Reset the legacy cosmetic 10 GiB placeholder to '0' (unlimited / volume-backed)."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE users SET total_capacity = '0' WHERE total_capacity = :legacy_quota"
        ),
        {"legacy_quota": LEGACY_DEFAULT_QUOTA_STR},
    )


def downgrade() -> None:
    """Restore legacy 10 GiB placeholder on uncapped rows."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE users SET total_capacity = :legacy_quota WHERE total_capacity = '0'"
        ),
        {"legacy_quota": LEGACY_DEFAULT_QUOTA_STR},
    )
