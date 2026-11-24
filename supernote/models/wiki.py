"""Shared wire-format DTOs and response VOs for the LLM Wiki API and MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse

__all__ = [
    "WikiCompileResponseVO",
    "WikiDeleteResponseVO",
    "WikiIndexEntryVO",
    "WikiIndexResponseVO",
    "WikiLintIssueDTO",
    "WikiLintIssueResponseVO",
    "WikiLintListVO",
    "WikiPageDTO",
    "WikiPageListVO",
    "WikiPageResponseVO",
    "WikiRevisionDTO",
    "WikiRevisionsResponseVO",
    "WikiSearchHitDTO",
    "WikiSearchResponseVO",
    "WikiSourceRefDTO",
    "WikiStatusDTO",
    "WikiStatusResponseVO",
]


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

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        if not isinstance(d, dict):
            raise ValueError("source_ref must be an object")
        for key in ("source_type", "source_key"):
            val = d.get(key)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{key} must be a non-empty string")
        for key in ("file_id", "last_event_seq"):
            if (val := d.get(key)) is not None and (
                isinstance(val, bool) or not isinstance(val, int)
            ):
                raise ValueError(f"{key} must be an integer")
        if (deleted := d.get("is_source_deleted")) is not None and not isinstance(
            deleted, bool
        ):
            raise ValueError("is_source_deleted must be a boolean")
        return {k: v for k, v in d.items() if v is not None}


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
class WikiIndexEntryVO(DataClassJSONMixin):
    """Compact metadata entry returned by `get_wiki_index` (omits body and graph)."""

    slug: str
    title: str
    page_kind: str
    summary: str
    version: int
    update_time: int

    @classmethod
    def from_page(cls, page: WikiPageDTO) -> WikiIndexEntryVO:
        """Project a full `WikiPageDTO` to a compact index entry."""
        return cls(
            slug=page.slug,
            title=page.title,
            page_kind=page.page_kind,
            summary=page.summary,
            version=page.version,
            update_time=page.update_time,
        )


@dataclass
class WikiIndexResponseVO(BaseResponse):
    """Response VO for `get_wiki_index`."""

    entries: list[WikiIndexEntryVO] = field(default_factory=list)


@dataclass
class WikiPageListVO(BaseResponse):
    """Response VO for listing active wiki pages."""

    pages: list[WikiPageDTO] = field(default_factory=list)


@dataclass
class WikiPageResponseVO(BaseResponse):
    """Response VO wrapping a single wiki page."""

    page: WikiPageDTO | None = None


@dataclass
class WikiRevisionsResponseVO(BaseResponse):
    """Response VO for listing immutable page revisions."""

    revisions: list[WikiRevisionDTO] = field(default_factory=list)


@dataclass
class WikiSearchResponseVO(BaseResponse):
    """Response VO for wiki lexical/alias search."""

    hits: list[WikiSearchHitDTO] = field(default_factory=list)


@dataclass
class WikiStatusResponseVO(BaseResponse):
    """Response VO wrapping per-user wiki status."""

    status: WikiStatusDTO | None = None


@dataclass
class WikiCompileResponseVO(BaseResponse):
    """Response VO for `POST /api/extended/wiki/compile`."""

    mode: str = "incremental"
    events_processed: int | None = None
    pages_updated: int | None = None
    skipped_policy_pages: int | None = None
    lint_issues_open: int | None = None
    status: str | None = None
    issues: list[WikiLintIssueDTO] | None = None


@dataclass
class WikiLintListVO(BaseResponse):
    """Response VO for listing wiki lint issues."""

    issues: list[WikiLintIssueDTO] = field(default_factory=list)


@dataclass
class WikiLintIssueResponseVO(BaseResponse):
    """Response VO wrapping a single wiki lint issue."""

    issue: WikiLintIssueDTO | None = None


@dataclass
class WikiDeleteResponseVO(BaseResponse):
    """Response VO for soft-deleting a wiki page."""

    deleted: bool = True
