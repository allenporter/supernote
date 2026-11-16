"""Migrate generated summaries to AI Summaries Digest category

Revision ID: f3b4c5d6e7f8
Revises: e8f9a0b1c2d3
Create Date: 2026-11-16 03:05:00.000000

"""

import hashlib
import time
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from supernote.server.utils.paths import (
    AI_SUMMARIES_GROUP_NAME,
    flatten_vfs_path,
    get_ai_summaries_group_id,
    get_summary_id,
)

# revision identifiers, used by Alembic.
revision: str = "f3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AI_GROUP_MD5 = hashlib.md5(AI_SUMMARIES_GROUP_NAME.encode("utf-8")).hexdigest()
_EPOCH_OFFSET_MS = 1609459200000
_MAX_PATH_DEPTH = 50


def _has_annotations(row: sa.Row) -> bool:
    return any(
        (val or "").strip()
        for val in (
            row.comment_str,
            row.comment_handwrite_name,
            row.handwrite_inner_name,
        )
    )


def _resolve_file_state(
    bind: sa.Connection, user_id: int, file_id: int
) -> tuple[str | None, bool]:
    """Return `(flattened_active_path, exists_inactive_in_vfs)` for `(user_id, file_id)`."""
    node = bind.execute(
        sa.text(
            "SELECT id, directory_id, file_name, is_folder, is_active "
            "FROM f_user_file WHERE user_id = :uid AND id = :fid"
        ),
        {"uid": user_id, "fid": file_id},
    ).fetchone()
    if node is None or node.is_folder == "Y":
        return None, False
    if node.is_active != "Y":
        return None, True

    parts = [node.file_name]
    curr_dir = int(node.directory_id)
    visited = {int(node.id)}
    while curr_dir != 0 and len(visited) <= _MAX_PATH_DEPTH and curr_dir not in visited:
        visited.add(curr_dir)
        parent = bind.execute(
            sa.text(
                "SELECT id, directory_id, file_name, is_active "
                "FROM f_user_file WHERE user_id = :uid AND id = :did"
            ),
            {"uid": user_id, "did": curr_dir},
        ).fetchone()
        if parent is None:
            break
        if parent.is_active != "Y":
            return None, True
        parts.insert(0, parent.file_name)
        curr_dir = int(parent.directory_id)

    return flatten_vfs_path("/".join(parts)) or node.file_name, False


def upgrade() -> None:
    """Migrate generated summaries to AI Summaries and soft-delete stale transcripts/groups."""
    bind = op.get_bind()
    now_ms = int(time.time() * 1000)
    max_existing = int(
        bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM f_summary")).scalar_one()
    )
    next_id = max(max_existing + 1, max(1, (now_ms - _EPOCH_OFFSET_MS) << 22))
    file_cache: dict[tuple[int, int], tuple[str | None, bool]] = {}
    ensured_groups: dict[int, str] = {}

    def alloc_id() -> int:
        nonlocal next_id
        allocated = next_id
        next_id += 1
        return allocated

    def file_state(user_id: int, file_id: int) -> tuple[str | None, bool]:
        key = (user_id, file_id)
        if key not in file_cache:
            file_cache[key] = _resolve_file_state(bind, user_id, file_id)
        return file_cache[key]

    def soft_delete(user_id: int, row_id: int) -> None:
        bind.execute(
            sa.text(
                "UPDATE f_summary SET is_deleted = :t, last_modified_time = :now, "
                "update_time = :now WHERE user_id = :uid AND id = :id"
            ),
            {"t": True, "now": now_ms, "uid": user_id, "id": row_id},
        )

    def detach_file(user_id: int, row_id: int) -> None:
        bind.execute(
            sa.text(
                "UPDATE f_summary SET file_id = NULL, update_time = :now "
                "WHERE user_id = :uid AND id = :id"
            ),
            {"now": now_ms, "uid": user_id, "id": row_id},
        )

    def ensure_ai_group(user_id: int) -> str:
        if user_id in ensured_groups:
            return ensured_groups[user_id]
        group_uuid = get_ai_summaries_group_id(user_id)
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
            bind.execute(
                sa.text(
                    "INSERT INTO f_summary "
                    "(id, user_id, name, unique_identifier, is_summary_group, md5_hash, "
                    "creation_time, last_modified_time, is_deleted, create_time, update_time) "
                    "VALUES (:id, :uid, :name, :uuid, :t, :md5, :now, :now, :f, :now, :now)"
                ),
                {
                    "id": alloc_id(),
                    "uid": user_id,
                    "name": AI_SUMMARIES_GROUP_NAME,
                    "uuid": group_uuid,
                    "t": True,
                    "f": False,
                    "md5": _AI_GROUP_MD5,
                    "now": now_ms,
                },
            )
        ensured_groups[user_id] = group_uuid
        return group_uuid

    def resolve_parent(user_id: int, parent: str | None) -> str:
        if parent == "":
            return ""
        if parent and not parent.endswith("-group"):
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM f_summary WHERE user_id = :uid AND unique_identifier = :p "
                    "AND is_deleted = :f AND is_summary_group = :t"
                ),
                {"uid": user_id, "p": parent, "f": False, "t": True},
            ).fetchone()
            if exists is not None:
                return parent
        return ensure_ai_group(user_id)

    active_leaves = list(
        bind.execute(
            sa.text(
                "SELECT * FROM f_summary WHERE is_deleted = :f AND is_summary_group = :f"
            ),
            {"f": False},
        )
    )
    active_by_uuid = {
        (int(r.user_id), str(r.unique_identifier)): r
        for r in active_leaves
        if r.unique_identifier
    }

    by_file: dict[tuple[int, int], list[sa.Row]] = defaultdict(list)
    for row in active_leaves:
        user_id = int(row.user_id)
        file_id = int(row.file_id) if row.file_id is not None else None
        uid = row.unique_identifier or ""
        if (row.data_source or "").upper() == "OCR" or uid.endswith("-transcript"):
            if _has_annotations(row):
                if file_id is not None and file_state(user_id, file_id)[0] is None:
                    detach_file(user_id, int(row.id))
            else:
                soft_delete(user_id, int(row.id))
            continue

        if not (
            uid.endswith("-summary")
            or (file_id is not None and uid == get_summary_id(user_id, file_id))
        ):
            continue
        if file_id is None:
            if not _has_annotations(row):
                soft_delete(user_id, int(row.id))
            continue
        by_file[(user_id, file_id)].append(row)

    for (user_id, file_id), rows in sorted(by_file.items()):
        source_path, exists_inactive = file_state(user_id, file_id)
        if source_path is None:
            for row in rows:
                if _has_annotations(row):
                    detach_file(user_id, int(row.id))
                else:
                    soft_delete(user_id, int(row.id))
            if exists_inactive:
                bind.execute(
                    sa.text(
                        "DELETE FROM f_system_task "
                        "WHERE file_id = :fid AND task_type = 'SUMMARY_GENERATION'"
                    ),
                    {"fid": file_id},
                )
            continue

        canonical_uuid = get_summary_id(user_id, file_id)
        canonical_row = active_by_uuid.get((user_id, canonical_uuid))
        if canonical_row is not None:
            target_parent = resolve_parent(
                user_id, canonical_row.parent_unique_identifier
            )
            md5 = canonical_row.md5_hash or (
                hashlib.md5(canonical_row.content.encode("utf-8")).hexdigest()
                if canonical_row.content
                else None
            )
            if (
                canonical_row.file_id,
                canonical_row.parent_unique_identifier,
                canonical_row.source_path,
                canonical_row.md5_hash,
            ) != (file_id, target_parent, source_path, md5):
                bind.execute(
                    sa.text(
                        "UPDATE f_summary SET file_id = :fid, parent_unique_identifier = :parent, "
                        "source_path = :path, md5_hash = :md5, last_modified_time = :now, "
                        "update_time = :now WHERE user_id = :uid AND id = :id"
                    ),
                    {
                        "fid": file_id,
                        "parent": target_parent,
                        "path": source_path,
                        "md5": md5,
                        "now": now_ms,
                        "uid": user_id,
                        "id": int(canonical_row.id),
                    },
                )
            kept_id = canonical_row.id
        else:
            winner = max(
                rows,
                key=lambda r: (
                    int(r.last_modified_time or r.update_time or r.create_time or 0),
                    int(r.id),
                ),
            )
            target_parent = resolve_parent(user_id, winner.parent_unique_identifier)
            bind.execute(
                sa.text(
                    "DELETE FROM f_summary WHERE user_id = :uid AND unique_identifier = :uuid"
                ),
                {"uid": user_id, "uuid": canonical_uuid},
            )
            md5 = winner.md5_hash or (
                hashlib.md5(winner.content.encode("utf-8")).hexdigest()
                if winner.content
                else None
            )
            bind.execute(
                sa.text(
                    "INSERT INTO f_summary "
                    "(id, user_id, file_id, name, unique_identifier, parent_unique_identifier, "
                    "content, source_path, data_source, source_type, is_summary_group, description, "
                    "tags, md5_hash, extra_metadata, comment_str, comment_handwrite_name, "
                    "handwrite_inner_name, handwrite_md5, creation_time, last_modified_time, "
                    "is_deleted, create_time, update_time, author) "
                    "VALUES (:id, :uid, :fid, :name, :uuid, :parent, :content, :path, :ds, :st, :f, "
                    ":desc, :tags, :md5, :meta, :cstr, :chw, :hin, :hmd5, :ctime, :now, :f, :now, :now, :author)"
                ),
                {
                    "id": alloc_id(),
                    "uid": user_id,
                    "fid": file_id,
                    "name": winner.name,
                    "uuid": canonical_uuid,
                    "parent": target_parent,
                    "content": winner.content,
                    "path": source_path,
                    "ds": winner.data_source,
                    "st": winner.source_type,
                    "f": False,
                    "desc": winner.description,
                    "tags": winner.tags,
                    "md5": md5,
                    "meta": winner.extra_metadata,
                    "cstr": winner.comment_str,
                    "chw": winner.comment_handwrite_name,
                    "hin": winner.handwrite_inner_name,
                    "hmd5": winner.handwrite_md5,
                    "ctime": winner.creation_time or winner.create_time or now_ms,
                    "now": now_ms,
                    "author": winner.author,
                },
            )
            soft_delete(user_id, int(winner.id))
            kept_id = winner.id

        for row in rows:
            if row.id != kept_id and not _has_annotations(row):
                soft_delete(user_id, int(row.id))

    non_empty_parents = {
        (int(r.user_id), str(r.parent_unique_identifier))
        for r in bind.execute(
            sa.text(
                "SELECT user_id, parent_unique_identifier FROM f_summary "
                "WHERE is_deleted = :f AND is_summary_group = :f "
                "AND parent_unique_identifier IS NOT NULL AND parent_unique_identifier != '' "
                "GROUP BY user_id, parent_unique_identifier"
            ),
            {"f": False},
        )
    }
    for g in bind.execute(
        sa.text(
            "SELECT id, user_id, unique_identifier, comment_str, comment_handwrite_name, "
            "handwrite_inner_name FROM f_summary "
            "WHERE is_deleted = :f AND is_summary_group = :t AND unique_identifier LIKE '%-group'"
        ),
        {"f": False, "t": True},
    ):
        g_uid = int(g.user_id)
        g_uuid = str(g.unique_identifier)
        if (
            g_uuid.endswith("-group")
            and not _has_annotations(g)
            and (g_uid, g_uuid) not in non_empty_parents
        ):
            soft_delete(g_uid, int(g.id))


def downgrade() -> None:
    """Non-destructive data migration; leave canonical Digest records intact on downgrade."""
    pass
