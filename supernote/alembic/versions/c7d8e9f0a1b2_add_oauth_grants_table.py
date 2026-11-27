"""Add oauth_grants and move OAuth refresh tokens out of key_values

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-11-23 12:00:00.000000

Each live `mcp:refresh_token:*` entry becomes a grant holding the token's SHA-256,
so connected clients stay connected. Plaintext `mcp:access_token:*` entries are
dropped: they expire within the hour and clients refresh them. Payloads that
still carry an email `user_id` are resolved here.

Downgrade drops the table, so clients must authorize again.
"""

import hashlib
import json
import secrets
import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFRESH_PREFIX = "mcp:refresh_token:"
_ACCESS_PREFIX = "mcp:access_token:"


def upgrade() -> None:
    """Create oauth_grants and convert stored refresh tokens into grants."""
    op.create_table(
        "oauth_grants",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=2048), nullable=False),
        sa.Column("scopes", sa.String(length=1024), nullable=False),
        sa.Column("access_token_hash", sa.String(length=64), nullable=True),
        sa.Column("access_expires_at", sa.Integer(), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_index(
        op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_grants_access_token_hash"),
        "oauth_grants",
        ["access_token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_grants_refresh_token_hash"),
        "oauth_grants",
        ["refresh_token_hash"],
        unique=False,
    )

    conn = op.get_bind()
    now = int(time.time())
    user_ids: dict[str, int] = {}
    for user_row in conn.execute(sa.text("SELECT id, email FROM users")):
        user_ids[str(user_row.id)] = user_row.id
        user_ids[user_row.email] = user_row.id
    rows = conn.execute(
        sa.text(
            "SELECT key, value, expiry FROM key_values WHERE substr(key, 1, :n) = :p"
        ),
        {"n": len(_REFRESH_PREFIX), "p": _REFRESH_PREFIX},
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        user_id = user_ids.get(str(payload.get("user_id")))
        try:
            expires_at = int(payload.get("expires_at") or row.expiry or 0)
        except (TypeError, ValueError):
            continue
        client_id = payload.get("client_id")
        scopes = payload.get("scopes") or []
        if (
            user_id is None
            or expires_at <= now
            or not isinstance(client_id, str)
            or not isinstance(scopes, list)
        ):
            continue
        token = row.key.removeprefix(_REFRESH_PREFIX)
        if not token:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO oauth_grants (user_id, id, client_id, scopes, "
                "refresh_token_hash, created_at, expires_at) "
                "VALUES (:user_id, :id, :client_id, :scopes, :hash, :now, :expires_at)"
            ),
            {
                "user_id": user_id,
                "id": secrets.token_hex(8),
                "client_id": client_id,
                "scopes": " ".join(map(str, scopes)),
                "hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "now": now,
                "expires_at": expires_at,
            },
        )
    for prefix in (_REFRESH_PREFIX, _ACCESS_PREFIX):
        conn.execute(
            sa.text("DELETE FROM key_values WHERE substr(key, 1, :n) = :p"),
            {"n": len(prefix), "p": prefix},
        )


def downgrade() -> None:
    """Drop oauth_grants; clients authorize again."""
    op.drop_index(op.f("ix_oauth_grants_refresh_token_hash"), table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_access_token_hash"), table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_user_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
