"""SQLAlchemy ORM models for the per-user LLM Wiki (`f_wiki_*`).

Defines seven multi-user tables keyed with non-nullable `user_id` in every
primary key and unique constraint/index:
- `WikiPageDO` (`f_wiki_page`): current wiki page state, claims, and concurrency version
- `WikiRevisionDO` (`f_wiki_revision`): immutable revision snapshots and audit trail
- `WikiAliasDO` (`f_wiki_alias`): canonical entity/slug alias map for OCR normalization
- `WikiLinkDO` (`f_wiki_link`): directed `[[wikilink]]` edges for graph traversal and lint
- `WikiSourceRefDO` (`f_wiki_source_ref`): provenance bindings to note pages and schedule tasks
- `WikiCheckpointDO` (`f_wiki_checkpoint`): per-user event cursor, backfill cursor, and token budget
- `WikiLintIssueDO` (`f_wiki_lint_issue`): deduplicated structural/semantic lint findings and proposals

Foreign-key rationale: matching `f_user_event` and `f_summary`, `user_id` omits a
`ForeignKey("users.id")` constraint so wiki tables stay decoupled from core auth
fixtures and support explicit service-level cleanup (`WikiService.delete_user_wiki`).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id

__all__ = [
    "WikiAliasDO",
    "WikiCheckpointDO",
    "WikiLinkDO",
    "WikiLintIssueDO",
    "WikiPageDO",
    "WikiRevisionDO",
    "WikiSourceRefDO",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


class WikiPageDO(Base):
    """Compiled or user/agent-authored personal wiki page (`f_wiki_page`).

    Tombstone revival invariant: `uq_f_wiki_page_user_slug` enforces one durable
    `page_id` per `(user_id, slug)` so `f_wiki_revision` audit history stays
    unified across delete/recreate cycles. Re-creating a soft-deleted slug must
    revive the existing `(user_id, page_id)` row in place (`is_deleted=False`,
    incremented `version`, and a new `WikiRevisionDO` snapshot).
    """

    __tablename__ = "f_wiki_page"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_f_wiki_page_user_slug"),
        Index(
            "ix_f_wiki_page_user_kind_updated",
            "user_id",
            "page_kind",
            "update_time",
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID (leading PK column covers single-tenant prefix scans)."""

    page_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_id, nullable=False
    )
    """Stable 64-bit Snowflake page identifier."""

    slug: Mapped[str] = mapped_column(String(191), nullable=False)
    """Canonical plural-prefixed slug (191-char limit keeps UTF-8 index keys compact)."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    """Human-readable page title."""

    page_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="topic")
    """Taxonomy kind (`index`, `log`, `source_digest`, `project`, `entity`, `topic`)."""

    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    """One-line catalog summary surfaced in the compact wiki index."""

    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Rendered Markdown body with `[[wikilinks]]` and source citations."""

    claims_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    """Bi-temporal structured claim objects (`active`, `superseded`, or `retracted`)."""

    edit_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    """Compiler write policy (`auto`, `protected_prose`, or `locked`)."""

    last_author_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="compiler"
    )
    """Origin of the latest revision (`compiler`, `agent`, or `user`)."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Monotonic optimistic-concurrency version checked on `PUT` / MCP upserts."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Soft-delete tombstone; revived in place when the same slug is recreated."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms
    )
    """Creation timestamp in UTC epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms, onupdate=_now_ms
    )
    """Last-modified timestamp in UTC epoch milliseconds."""


class WikiRevisionDO(Base):
    """Immutable revision snapshot and audit trail (`f_wiki_revision`)."""

    __tablename__ = "f_wiki_revision"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "page_id", "revision_no", name="uq_f_wiki_revision_page_rev"
        ),
        Index("ix_f_wiki_revision_user_event", "user_id", "source_event_seq"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    revision_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_id, nullable=False
    )
    """Immutable 64-bit Snowflake revision identifier."""

    page_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Target `f_wiki_page.page_id` (covered by `uq_f_wiki_revision_page_rev`)."""

    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    """1-based monotonic revision number matching `WikiPageDO.version`."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    """Page title captured at this revision."""

    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    """Markdown body captured at this revision."""

    claims_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    """Structured claims snapshot captured at this revision."""

    author_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    """Actor category (`compiler`, `agent`, or `user`)."""

    author_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """Canonical actor string (e.g. `user:web`, `oauth:<client>`, `api_key:<id>`)."""

    change_summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    """Short human-readable description of what changed in this revision."""

    source_event_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """High-water `f_user_event.seq` compiled into this revision, when event-driven."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms
    )
    """Revision creation timestamp in UTC epoch milliseconds."""


class WikiAliasDO(Base):
    """Canonical entity/slug alias map for handwriting OCR normalization (`f_wiki_alias`)."""

    __tablename__ = "f_wiki_alias"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "normalized_alias", name="uq_f_wiki_alias_user_norm"
        ),
        Index("ix_f_wiki_alias_user_page", "user_id", "page_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    alias_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_id, nullable=False
    )
    """64-bit Snowflake alias identifier."""

    page_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Canonical `f_wiki_page.page_id` resolved by this alias."""

    alias_text: Mapped[str] = mapped_column(String(255), nullable=False)
    """Original display form of the alias."""

    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    """Case-folded, whitespace-normalized lookup key."""

    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="compiler")
    """How the alias was added (`compiler`, `user`, or `lint_approved`)."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms
    )
    """Creation timestamp in UTC epoch milliseconds."""


class WikiLinkDO(Base):
    """Directed `[[wikilink]]` edge between wiki pages (`f_wiki_link`)."""

    __tablename__ = "f_wiki_link"
    __table_args__ = (
        Index("ix_f_wiki_link_user_target", "user_id", "target_slug"),
        Index("ix_f_wiki_link_user_target_page", "user_id", "target_page_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    from_page_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, nullable=False
    )
    """Source `f_wiki_page.page_id` containing the outbound link."""

    target_slug: Mapped[str] = mapped_column(
        String(191), primary_key=True, nullable=False
    )
    """Normalized target slug extracted from `[[target_slug|label]]`."""

    target_page_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Resolved target `f_wiki_page.page_id`, or `None` when the link is broken."""

    link_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Optional display label override from `[[slug|label]]`."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms, onupdate=_now_ms
    )
    """Last-refreshed timestamp in UTC epoch milliseconds."""


class WikiSourceRefDO(Base):
    """Provenance binding between a wiki page and note pages or schedule tasks (`f_wiki_source_ref`)."""

    __tablename__ = "f_wiki_source_ref"
    __table_args__ = (
        Index(
            "ix_f_wiki_source_ref_user_entity",
            "user_id",
            "source_type",
            "source_key",
        ),
        Index("ix_f_wiki_source_ref_user_file", "user_id", "file_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    page_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Wiki page `f_wiki_page.page_id` citing this source."""

    source_type: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False
    )
    """Source domain (`note_page` or `schedule_task`)."""

    source_key: Mapped[str] = mapped_column(
        String(191), primary_key=True, nullable=False
    )
    """Stable source identifier (`{file_id}:{page_id}` or `{task_id}`)."""

    file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Associated VFS `file_id` for fast notebook-wide invalidation on rename/delete."""

    last_event_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Latest `f_user_event.seq` incorporated from this source."""

    is_source_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    """Marked `True` when the backing note page, file, or task is deleted."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms, onupdate=_now_ms
    )
    """Last-refreshed timestamp in UTC epoch milliseconds."""


class WikiCheckpointDO(Base):
    """Per-user durable compiler cursor, backfill progress, and daily token budget (`f_wiki_checkpoint`)."""

    __tablename__ = "f_wiki_checkpoint"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    last_sync_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """Opaque `EventLogService` sync token (`v1:{seq}`), single source of cursor truth."""

    pending_events_since_lint: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    """Count of compiled events since the last LLM semantic lint pass."""

    last_lint_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """UTC epoch milliseconds of the most recent completed lint pass."""

    backfill_file_cursor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Legacy `UserFileDO.id` backfill cursor (superseded by `backfill_page_cursor`)."""

    backfill_page_cursor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """Opaque chronological page cursor (`ts_ms:file_id:page_index:row_id`) for global page-date backfill."""

    tokens_used_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Cumulative LLM tokens consumed during `budget_day_utc`."""

    budget_day_utc: Mapped[str | None] = mapped_column(String(10), nullable=True)
    """UTC calendar day (`YYYY-MM-DD`) scoping `tokens_used_day`."""

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    """Worker state (`idle`, `compiling`, `backfilling`, `paused`, or `error`)."""

    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """Truncated diagnostic message from the last failed compile or lint pass."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms, onupdate=_now_ms
    )
    """Last-modified timestamp in UTC epoch milliseconds."""


class WikiLintIssueDO(Base):
    """Deduplicated structural or semantic lint finding and merge proposal (`f_wiki_lint_issue`)."""

    __tablename__ = "f_wiki_lint_issue"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_f_wiki_lint_user_dedup"),
        Index("ix_f_wiki_lint_user_status", "user_id", "status", "issue_type"),
        Index("ix_f_wiki_lint_user_page", "user_id", "page_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    issue_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=next_id, nullable=False
    )
    """64-bit Snowflake lint issue identifier."""

    dedup_key: Mapped[str] = mapped_column(String(191), nullable=False)
    """Deterministic key preventing duplicate open rows across repeated lint passes."""

    issue_type: Mapped[str] = mapped_column(String(48), nullable=False)
    """Finding kind (`broken_link`, `orphan_page`, `stale_source`, `contradiction`, `alias_merge_proposal`)."""

    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warn")
    """Severity level (`info`, `warn`, or `error`)."""

    page_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Primary `f_wiki_page.page_id` affected by this issue."""

    target_page_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Secondary `f_wiki_page.page_id` for cross-page contradictions or alias merges."""

    description: Mapped[str] = mapped_column(Text, nullable=False)
    """Human-readable summary of the lint finding."""

    proposal_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Optional structured resolution payload (e.g. canonical target slug for alias merge)."""

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    """Triage state (`open`, `resolved`, or `dismissed`)."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms
    )
    """Creation timestamp in UTC epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=_now_ms, onupdate=_now_ms
    )
    """Last-modified timestamp in UTC epoch milliseconds."""
