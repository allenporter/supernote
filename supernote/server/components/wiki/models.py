"""Pure domain DTOs, slug/wikilink helpers, and exceptions for the LLM Wiki."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = [
    "WikiConflictError",
    "WikiError",
    "WikiLintIssueDTO",
    "WikiNotFoundError",
    "WikiPageDTO",
    "WikiPolicyError",
    "WikiRevisionDTO",
    "WikiSearchHitDTO",
    "WikiSourceRefDTO",
    "WikiStatusDTO",
    "WikiUpsertInput",
]

VALID_AUTHOR_KINDS: frozenset[str] = frozenset({"compiler", "agent", "user"})
VALID_PAGE_KINDS: frozenset[str] = frozenset(
    {"index", "log", "source_digest", "project", "entity", "topic"}
)
VALID_EDIT_POLICIES: frozenset[str] = frozenset({"auto", "protected_prose", "locked"})

_SLUG_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
_WHITESPACE_RE = re.compile(r"\s+")


class WikiError(Exception):
    """Base exception for wiki domain errors."""


class WikiNotFoundError(WikiError):
    """Raised when a requested wiki page or lint issue does not exist."""


class WikiConflictError(WikiError):
    """Raised when optimistic-concurrency `expected_version` does not match."""

    def __init__(self, slug: str, expected: int, actual: int) -> None:
        self.slug = slug
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Version conflict on wiki page {slug!r}: expected {expected}, actual {actual}"
        )


class WikiPolicyError(WikiError):
    """Raised when a compiler write violates a page's `edit_policy`."""


def normalize_slug(raw_slug: str) -> str:
    """Normalize and validate a canonical wiki slug (e.g. ``projects/q3-plan``).

    Rejects empty slugs, path traversal segments (`..`), leading/trailing slashes,
    and characters outside `[a-z0-9._-/]`.
    """
    cleaned = raw_slug.strip().strip("/").lower()
    if not cleaned or len(cleaned) > 191:
        raise ValueError(f"Invalid wiki slug: {raw_slug!r}")
    segments = cleaned.split("/")
    for seg in segments:
        if seg in ("", ".", "..") or not _SLUG_SEGMENT_RE.fullmatch(seg):
            raise ValueError(f"Invalid wiki slug segment {seg!r} in {raw_slug!r}")
    return "/".join(segments)


def normalize_alias(alias_text: str) -> str:
    """Case-fold and collapse whitespace for canonical alias matching."""
    normalized = _WHITESPACE_RE.sub(" ", alias_text.strip()).lower()
    if not normalized:
        raise ValueError("Alias text must be non-empty")
    return normalized


def extract_wikilinks(body_md: str) -> list[tuple[str, str | None]]:
    """Extract deduplicated `(normalized_target_slug, link_label)` pairs from Markdown."""
    seen: dict[str, str | None] = {}
    for match in _WIKILINK_RE.finditer(body_md):
        raw_target = match.group(1)
        raw_label = match.group(2)
        try:
            slug = normalize_slug(raw_target)
        except ValueError:
            continue
        if slug not in seen:
            seen[slug] = raw_label.strip() if raw_label else None
    return list(seen.items())


@dataclass
class WikiSourceRefDTO(DataClassJSONMixin):
    """Provenance reference linking a wiki page to a note page or schedule task."""

    source_type: str
    """Source kind (`note_page` or `schedule_task`)."""
    source_key: str
    """Stable identifier (`{file_id}:{page_id}` or `{task_id}`)."""
    file_id: int | None = None
    """Associated VFS `file_id`, when applicable."""
    last_event_seq: int | None = None
    """Latest incorporated `f_user_event.seq`."""
    is_source_deleted: bool = False
    """True when the backing note page, file, or task was deleted."""


@dataclass
class WikiPageDTO(DataClassJSONMixin):
    """Domain representation of a compiled or user-authored wiki page."""

    page_id: int
    slug: str
    title: str
    page_kind: str
    summary: str
    body_md: str
    claims: list[dict[str, Any]]
    edit_policy: str
    last_author_kind: str
    version: int
    create_time: int
    update_time: int
    aliases: list[str] = field(default_factory=list)
    outbound_links: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    source_refs: list[WikiSourceRefDTO] = field(default_factory=list)


@dataclass
class WikiRevisionDTO(DataClassJSONMixin):
    """Immutable snapshot of one wiki page revision."""

    revision_id: int
    page_id: int
    revision_no: int
    title: str
    body_md: str
    claims: list[dict[str, Any]]
    author_kind: str
    author_ref: str | None
    change_summary: str
    source_event_seq: int | None
    create_time: int


@dataclass
class WikiLintIssueDTO(DataClassJSONMixin):
    """Actionable structural or semantic wiki lint finding."""

    issue_id: int
    dedup_key: str
    issue_type: str
    severity: str
    page_id: int | None
    target_page_id: int | None
    description: str
    proposal: dict[str, Any] | None
    status: str
    create_time: int
    update_time: int


@dataclass
class WikiSearchHitDTO(DataClassJSONMixin):
    """Ranked wiki search hit with 1-hop neighbor slugs and source refs."""

    slug: str
    title: str
    page_kind: str
    summary: str
    score: float
    neighbor_slugs: list[str] = field(default_factory=list)
    source_refs: list[WikiSourceRefDTO] = field(default_factory=list)


@dataclass
class WikiStatusDTO(DataClassJSONMixin):
    """Per-user wiki inventory, cursor, budget, and lint summary."""

    page_count: int
    open_lint_count: int
    last_sync_token: str | None
    pending_events_since_lint: int
    tokens_used_day: int
    budget_day_utc: str | None
    status: str
    last_error: str | None


@dataclass
class WikiUpsertInput(DataClassJSONMixin):
    """Input payload for creating or updating a wiki page."""

    slug: str
    title: str
    body_md: str
    page_kind: str = "topic"
    summary: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source_refs: list[WikiSourceRefDTO] = field(default_factory=list)
    author_kind: str = "user"
    author_ref: str | None = None
    change_summary: str = ""
    expected_version: int | None = None
    edit_policy: str | None = None
    source_event_seq: int | None = None
