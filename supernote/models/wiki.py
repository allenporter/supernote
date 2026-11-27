"""Shared wire-format DTOs and response VOs for the LLM Wiki API and MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse

__all__ = [
    "WikiCompileMode",
    "WikiCompileResponseVO",
    "WikiDeleteResponseVO",
    "WikiDiagnosticsResponseVO",
    "WikiDryRunOpDTO",
    "WikiDryRunPageDTO",
    "WikiDryRunResponseVO",
    "WikiIndexEntryVO",
    "WikiIndexResponseVO",
    "WikiLintIssueDTO",
    "WikiLintIssueResponseVO",
    "WikiLintListVO",
    "WikiNotebookCoverageDTO",
    "WikiPageDTO",
    "WikiPageListVO",
    "WikiPageResponseVO",
    "WikiRevisionDTO",
    "WikiRevisionsResponseVO",
    "WikiSearchHitDTO",
    "WikiSearchResponseVO",
    "WikiSourceRefDTO",
    "WikiSourceType",
    "WikiStatusDTO",
    "WikiStatusResponseVO",
]


class WikiSourceType(StrEnum):
    """Supported provenance source kinds for `WikiSourceRefDTO`."""

    NOTE_PAGE = "note_page"
    SCHEDULE_TASK = "schedule_task"


@dataclass
class WikiSourceRefDTO(DataClassJSONMixin):
    """Provenance reference linking a wiki page to a note page or schedule task."""

    source_type: WikiSourceType
    """Source kind (`note_page` or `schedule_task`)."""
    source_key: str
    """Stable identifier (`{file_id}:{page_id}` or `{task_id}`)."""
    file_id: int | None = None
    """Associated VFS `file_id`, when applicable."""
    last_event_seq: int | None = None
    """Latest incorporated `f_user_event.seq`."""
    is_source_deleted: bool = False
    """True when the backing note page, file, or task was deleted."""
    file_name: str | None = None
    """Resolved notebook filename for `note_page` citations, when active."""
    page_index: int | None = None
    """Resolved 0-based page index for `note_page` citations, when available."""
    task_title: str | None = None
    """Resolved schedule task title for `schedule_task` citations, when active."""

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, WikiSourceType):
            self.source_type = WikiSourceType(self.source_type)
        if not self.source_key.strip():
            raise ValueError("source_key must be non-empty")


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
    backfill_remaining_files: int = 0
    backfill_total_files: int = 0
    backfill_remaining_pages: int = 0
    backfill_total_pages: int = 0
    backfill_untranscribed_files: int = 0
    backfill_next_files: list[str] = field(default_factory=list)


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


class WikiCompileMode(StrEnum):
    """Supported execution modes for `POST /api/extended/wiki/compile`."""

    INCREMENTAL = "incremental"
    BACKFILL = "backfill"
    BACKFILL_START = "backfill_start"
    BACKFILL_STOP = "backfill_stop"
    BACKFILL_RESET = "backfill_reset"
    LINT = "lint"


@dataclass
class WikiCompileResponseVO(BaseResponse):
    """Response VO for `POST /api/extended/wiki/compile`."""

    mode: WikiCompileMode = WikiCompileMode.INCREMENTAL
    events_processed: int | None = None
    pages_updated: int | None = None
    skipped_policy_pages: int | None = None
    lint_issues_open: int | None = None
    status: str | None = None
    issues: list[WikiLintIssueDTO] | None = None
    files_processed: list[str] = field(default_factory=list)
    updated_pages: list[str] = field(default_factory=list)
    remaining_files: int | None = None


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


@dataclass
class WikiNotebookCoverageDTO(DataClassJSONMixin):
    """Per-notebook OCR vs. wiki citation coverage for live quality debugging."""

    file_id: str
    file_name: str
    ocr_pages: int
    cited_pages: int
    avg_chars_per_page: int
    cited_slugs: list[str] = field(default_factory=list)


@dataclass
class WikiDiagnosticsResponseVO(BaseResponse):
    """Response VO for `GET /api/extended/wiki/diagnostics`."""

    notebooks: list[WikiNotebookCoverageDTO] = field(default_factory=list)


@dataclass
class WikiDryRunPageDTO(DataClassJSONMixin):
    """Summary of one source page fed into a dry-run compile turn."""

    source_id: str
    file_id: str
    file_path: str
    page_index: int
    page_date: str
    chars: int
    snippet: str
    source_key: str = ""
    text_content: str = ""


@dataclass
class WikiDryRunOpDTO(DataClassJSONMixin):
    """Dry-run evaluation of one `WikiPageOp` returned by the LLM."""

    slug: str
    title: str
    page_kind: str
    summary: str
    body_chars: int
    resolved_source_keys: list[str] = field(default_factory=list)
    dropped_source_keys: list[str] = field(default_factory=list)
    drop_reason: str | None = None
    body_md: str = ""


@dataclass
class WikiDryRunResponseVO(BaseResponse):
    """Response VO for `POST /api/extended/wiki/diagnostics/dry-run`."""

    pages_sent: list[WikiDryRunPageDTO] = field(default_factory=list)
    candidate_slugs: list[str] = field(default_factory=list)
    ops: list[WikiDryRunOpDTO] = field(default_factory=list)
    lint_proposals_count: int = 0
    elapsed_ms: int = 0
