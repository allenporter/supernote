"""Reparent uncategorized generated AI summaries into AI Summaries category

Revision ID: a4b5c6d7e8f9
Revises: f3b4c5d6e7f8
Create Date: 2026-11-23 03:55:00.000000

"""

import hashlib
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AI_SUMMARIES_GROUP_NAME = "AI Summaries"
_AI_GROUP_MD5 = hashlib.md5(_AI_SUMMARIES_GROUP_NAME.encode("utf-8")).hexdigest()
_EPOCH_OFFSET_MS = 1609459200000


def _summary_id(user_id: int, file_id: int) -> str:
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://supernote.local/summary/{user_id}/{file_id}"
    ).hex


def _ai_group_id(user_id: int) -> str:
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://supernote.local/ai-summaries-group/{user_id}"
    ).hex


def upgrade() -> None:
    """Move uncategorized server-generated AI summaries into the per-user AI Summaries group."""
    bind = op.get_bind()
    candidates = list(
        bind.execute(
            sa.text(
                "SELECT id, user_id, file_id, unique_identifier, data_source, "
                "last_modified_time, update_time FROM f_summary "
                "WHERE is_deleted = :f AND is_summary_group = :f AND file_id IS NOT NULL "
                "AND (parent_unique_identifier IS NULL OR parent_unique_identifier = '')"
            ),
            {"f": False},
        )
    )

    to_reparent: list[sa.Row] = []
    for row in candidates:
        user_id = int(row.user_id)
        file_id = int(row.file_id)
        uid = str(row.unique_identifier or "")
        source = (row.data_source or "").strip().upper()
        is_canonical_ai = uid == _summary_id(user_id, file_id)
        is_legacy_ai = (
            uid.endswith("-summary") and bool(source) and source not in {"OCR", "USER"}
        )
        if is_canonical_ai or is_legacy_ai:
            to_reparent.append(row)

    if not to_reparent:
        return

    now_ms = int(time.time() * 1000)
    max_existing = int(
        bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM f_summary")).scalar_one()
    )
    next_id = max(max_existing + 1, max(1, (now_ms - _EPOCH_OFFSET_MS) << 22))
    ensured_groups: dict[int, str] = {}

    def ensure_ai_group(user_id: int) -> str:
        nonlocal next_id
        if user_id in ensured_groups:
            return ensured_groups[user_id]
        group_uuid = _ai_group_id(user_id)
        existing = bind.execute(
            sa.text(
                "SELECT is_deleted, is_summary_group FROM f_summary "
                "WHERE user_id = :uid AND unique_identifier = :uuid"
            ),
            {"uid": user_id, "uuid": group_uuid},
        ).fetchone()
        if existing is None or existing.is_deleted or not existing.is_summary_group:
            if existing is not None:
                bind.execute(
                    sa.text(
                        "DELETE FROM f_summary WHERE user_id = :uid AND unique_identifier = :uuid"
                    ),
                    {"uid": user_id, "uuid": group_uuid},
                )
            group_id = next_id
            next_id += 1
            bind.execute(
                sa.text(
                    "INSERT INTO f_summary "
                    "(id, user_id, name, unique_identifier, is_summary_group, md5_hash, "
                    "creation_time, last_modified_time, is_deleted, create_time, update_time) "
                    "VALUES (:id, :uid, :name, :uuid, :t, :md5, :now, :now, :f, :now, :now)"
                ),
                {
                    "id": group_id,
                    "uid": user_id,
                    "name": _AI_SUMMARIES_GROUP_NAME,
                    "uuid": group_uuid,
                    "t": True,
                    "f": False,
                    "md5": _AI_GROUP_MD5,
                    "now": now_ms,
                },
            )
        ensured_groups[user_id] = group_uuid
        return group_uuid

    for row in to_reparent:
        user_id = int(row.user_id)
        group_uuid = ensure_ai_group(user_id)
        prev_mtime = max(int(row.last_modified_time or 0), int(row.update_time or 0))
        new_mtime = max(now_ms, prev_mtime + 1)
        bind.execute(
            sa.text(
                "UPDATE f_summary SET parent_unique_identifier = :parent, "
                "last_modified_time = :mtime, update_time = :mtime "
                "WHERE user_id = :uid AND id = :id"
            ),
            {
                "parent": group_uuid,
                "mtime": new_mtime,
                "uid": user_id,
                "id": int(row.id),
            },
        )


def downgrade() -> None:
    """Non-destructive data migration; leave category assignments intact on downgrade."""
    pass
