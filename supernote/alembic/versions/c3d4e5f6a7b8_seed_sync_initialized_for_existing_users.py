"""seed sync:initialized for existing users with active files

Revision ID: c3d4e5f6a7b8
Revises: a2b3c4d5e6f7
Create Date: 2026-10-26 00:00:00.000000

"""

import time
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYNC_INITIALIZED_TTL = 100 * 365 * 24 * 3600


def upgrade() -> None:
    """Seed sync:initialized:{user_id} for existing accounts that already have active files."""
    bind = op.get_bind()
    expiry = time.time() + SYNC_INITIALIZED_TTL
    bind.execute(
        sa.text(
            "INSERT INTO key_values (key, value, expiry) "
            "SELECT 'sync:initialized:' || CAST(user_id AS TEXT), '1', :expiry "
            "FROM f_user_file "
            "WHERE is_active = 'Y' AND is_folder = 'N' "
            "GROUP BY user_id "
            "ON CONFLICT(key) DO NOTHING"
        ),
        {"expiry": expiry},
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
