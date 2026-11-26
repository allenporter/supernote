"""Structured-output schemas and prompt builders for the LLM Wiki compiler.

High-level data flow for the two LLM prompts owned by this module:

1. **Incremental Compile & Backfill (`PromptId.WIKI_COMPILE` -> `WikiCompilePlan`)**
   - *Inputs*: the user's compact wiki index (`<user_index>`), top existing
     candidate pages with their `edit_policy` and `version` (`<candidate_pages>`),
     the batch of uncompiled domain events or backfill note pages (`<source_diff>`),
     and linked schedule task + notebook OCR snapshots (`<linked_context>`).
   - *Output*: a `WikiCompilePlan` JSON object containing `page_ops` (upserts
     mapped into `WikiUpsertInput` + `WikiSourceRefDTO`), `lint_proposals`
     (semantic issues recorded in `f_wiki_lint_issue`), and an optional
     `log_entry`.

2. **Semantic Health Audit (`PromptId.WIKI_LINT` -> `WikiLintReport`)**
   - *Inputs*: a batch of active wiki page summaries/aliases/claims
     (`<pages_batch>`) and current schedule task snapshots (`<task_snapshots>`).
   - *Output*: a `WikiLintReport` JSON object listing non-mutating findings
     (`contradiction`, `alias_merge_proposal`) that are stored in
     `f_wiki_lint_issue` for human or external-agent triage.

Prompt-injection defense: all untrusted user text (handwritten OCR, task titles,
existing page bodies) is fenced inside explicit XML boundary tags and escaped
with `sanitize_xml_payload`. Prompt templates use lightweight `{{name}}`
placeholders (not Jinja2) substituted in a single regex pass so user notes
containing `{{...}}` cannot trigger chained expansion.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from mashumaro.jsonschema import build_json_schema
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.wiki import WikiSourceType
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

from .models import WikiPageDTO

__all__ = [
    "WikiClaimOp",
    "WikiCompilePlan",
    "WikiLintIssueOp",
    "WikiLintProposalOp",
    "WikiLintProposalPayload",
    "WikiLintReport",
    "WikiPageOp",
    "WikiSourceRefOp",
    "build_compile_prompt",
    "build_lint_prompt",
    "get_compile_json_schema",
    "get_lint_json_schema",
    "parse_compile_plan",
    "parse_lint_report",
    "render_prompt_template",
    "sanitize_xml_payload",
    "select_candidate_pages",
]


@dataclass
class WikiSourceRefOp(DataClassJSONMixin):
    """A single provenance citation emitted inside a compiled wiki page op."""

    source_type: WikiSourceType = field(
        metadata={"description": "Source kind: 'note_page' or 'schedule_task'."}
    )
    source_key: str = field(
        metadata={
            "description": "Stable source identifier ('{file_id}:{page_id}' or '{task_id}')."
        }
    )
    file_id: int | None = field(
        default=None,
        metadata={"description": "Optional numeric VFS file ID for note sources."},
    )


@dataclass
class WikiClaimOp(DataClassJSONMixin):
    """A structured bi-temporal factual claim extracted from user sources."""

    text: str = field(
        metadata={"description": "Concise factual statement backed by source_refs."}
    )
    claim_id: str = field(
        default="",
        metadata={"description": "Optional stable claim identifier within the page."},
    )
    status: str = field(
        default="active",
        metadata={"description": "Claim status: 'active' or 'superseded'."},
    )
    valid_from: str = field(
        default="",
        metadata={"description": "Optional ISO-8601 date when the claim became true."},
    )
    invalid_at: str = field(
        default="",
        metadata={"description": "Optional ISO-8601 date when superseded."},
    )
    superseded_by_source: str = field(
        default="",
        metadata={"description": "Optional source_key that superseded this claim."},
    )


@dataclass
class WikiLintProposalPayload(DataClassJSONMixin):
    """Structured remediation metadata for a semantic lint proposal or issue."""

    canonical_slug: str = field(
        default="",
        metadata={"description": "Recommended canonical slug for alias merges."},
    )
    duplicate_slugs: list[str] = field(
        default_factory=list,
        metadata={"description": "Suspected duplicate slugs to merge or alias."},
    )
    conflicting_slugs: list[str] = field(
        default_factory=list,
        metadata={"description": "Wiki slugs involved in a factual contradiction."},
    )
    rationale: str = field(
        default="",
        metadata={"description": "Brief rationale explaining the proposed action."},
    )


@dataclass
class WikiPageOp(DataClassJSONMixin):
    """A single wiki page create/update operation emitted by `PromptId.WIKI_COMPILE`."""

    slug: str = field(
        metadata={
            "description": "Canonical plural-prefixed slug (e.g. 'projects/q3-plan')."
        }
    )
    title: str = field(metadata={"description": "Human-readable page heading."})
    body_md: str = field(
        metadata={
            "description": "Markdown body with [[slug]] wikilinks for cross-page links."
        }
    )
    page_kind: str = field(
        default="topic",
        metadata={
            "description": "Category: project, entity, topic, source_digest, index, or log."
        },
    )
    summary: str = field(
        default="",
        metadata={"description": "Concise one-line summary for index and search."},
    )
    aliases: list[str] = field(
        default_factory=list,
        metadata={"description": "Alternate names or OCR spellings for this page."},
    )
    claims: list[WikiClaimOp] = field(
        default_factory=list,
        metadata={"description": "Structured bi-temporal factual claims."},
    )
    source_refs: list[WikiSourceRefOp] = field(
        default_factory=list,
        metadata={"description": "Provenance citations backing this page update."},
    )
    change_summary: str = field(
        default="Incremental compile",
        metadata={"description": "Short changelog note stored on the revision row."},
    )


@dataclass
class WikiLintProposalOp(DataClassJSONMixin):
    """A semantic lint proposal emitted alongside a compile batch."""

    issue_type: str = field(
        metadata={
            "description": "Semantic issue kind (e.g. 'contradiction', 'alias_merge_proposal')."
        }
    )
    description: str = field(
        metadata={"description": "Human-readable explanation of the finding."}
    )
    proposal: WikiLintProposalPayload | None = field(
        default=None,
        metadata={"description": "Optional structured remediation metadata."},
    )


@dataclass
class WikiCompilePlan(DataClassJSONMixin):
    """Structured output schema for `PromptId.WIKI_COMPILE`."""

    page_ops: list[WikiPageOp] = field(
        default_factory=list,
        metadata={"description": "Wiki page upserts to apply for this batch."},
    )
    lint_proposals: list[WikiLintProposalOp] = field(
        default_factory=list,
        metadata={"description": "Non-mutating semantic lint proposals to record."},
    )
    log_entry: str = field(
        default="",
        metadata={"description": "Optional one-line summary for the wiki change log."},
    )


@dataclass
class WikiLintIssueOp(DataClassJSONMixin):
    """A single semantic health finding emitted by `PromptId.WIKI_LINT`."""

    issue_type: str = field(
        metadata={
            "description": "Semantic issue kind ('contradiction' or 'alias_merge_proposal')."
        }
    )
    description: str = field(
        metadata={"description": "Human-readable explanation citing conflicting slugs."}
    )
    severity: str = field(
        default="warn",
        metadata={"description": "Severity level ('info', 'warn', or 'error')."},
    )
    proposal: WikiLintProposalPayload | None = field(
        default=None,
        metadata={"description": "Optional structured merge or resolution proposal."},
    )


@dataclass
class WikiLintReport(DataClassJSONMixin):
    """Structured output schema for `PromptId.WIKI_LINT`."""

    issues: list[WikiLintIssueOp] = field(
        default_factory=list,
        metadata={"description": "Semantic health findings detected in the batch."},
    )


# XML delimiter tags used in `wiki_compile` and `wiki_lint` prompt templates to
# fence untrusted user data from system instructions. Any matching open/close
# tag inside untrusted payloads is escaped to `&lt;...` before substitution:
#   - `source_diff`:      (wiki_compile) newly transcribed note/task event diffs
#   - `linked_context`:   (wiki_compile) schedule task + linked notebook OCR snapshots
#   - `user_index`:       (wiki_compile) compact index of existing user wiki pages
#   - `candidate_pages`:  (wiki_compile) full bodies/metadata of top existing pages
#   - `pages_batch`:      (wiki_lint) batch of wiki page summaries/aliases/claims
#   - `task_snapshots`:   (wiki_lint) current schedule task states for drift checks
_BOUNDARY_TAG_RE = re.compile(
    r"<\s*(/?)\s*("
    r"source_diff"
    r"|linked_context"
    r"|user_index"
    r"|candidate_pages"
    r"|pages_batch"
    r"|task_snapshots"
    r")\b",
    re.IGNORECASE,
)

# Lightweight `{{name}}` placeholder syntax used in `wiki_*.md` prompt files.
# This is intentionally NOT Jinja2: replacing all placeholders in a single regex
# pass ensures untrusted note content containing `{{...}}` is never re-expanded
# or evaluated as template code.
_PLACEHOLDER_RE = re.compile(r"\{\{([a-z0-9_]+)\}\}")

_REQUIRED_STR_FIELDS: dict[str, tuple[str, ...]] = {
    "page_op": ("slug", "title", "body_md"),
    "source_ref": ("source_type", "source_key"),
    "claim": ("text",),
    "lint_item": ("issue_type", "description"),
}


def _strip_null_optionals(
    obj: Mapping[str, Any], *, required_strings: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Drop `None` optional keys (so defaults apply) and reject `None` required strings.

    Mashumaro coerces `None` to literal `"None"` for `str` fields and raises on
    `None` for `list` fields; normalizing at the LLM boundary prevents both.
    """
    cleaned: dict[str, Any] = {}
    for key, val in obj.items():
        if val is None:
            if key in required_strings:
                raise ValueError(f"Required string field {key!r} cannot be null")
            continue
        cleaned[key] = val
    for req in required_strings:
        if req not in cleaned or not isinstance(cleaned[req], str):
            raise ValueError(f"Required string field {req!r} must be a string")
    return cleaned


@lru_cache(maxsize=1)
def get_compile_json_schema() -> dict[str, Any]:
    """Return the JSON Schema dictionary for `WikiCompilePlan`."""
    return build_json_schema(WikiCompilePlan).to_dict()


@lru_cache(maxsize=1)
def get_lint_json_schema() -> dict[str, Any]:
    """Return the JSON Schema dictionary for `WikiLintReport`."""
    return build_json_schema(WikiLintReport).to_dict()


def parse_compile_plan(raw: Mapping[str, Any]) -> WikiCompilePlan:
    """Deserialize a raw LLM JSON dict into a typed `WikiCompilePlan`."""
    cleaned = _strip_null_optionals(raw)
    if "page_ops" in cleaned:
        if not isinstance(cleaned["page_ops"], list):
            raise ValueError("page_ops must be a list")
        ops = []
        for item in cleaned["page_ops"]:
            if not isinstance(item, Mapping):
                raise ValueError("page_ops entries must be objects")
            op = _strip_null_optionals(
                item, required_strings=_REQUIRED_STR_FIELDS["page_op"]
            )
            if "source_refs" in op:
                if not isinstance(op["source_refs"], list):
                    raise ValueError("source_refs must be a list")
                op["source_refs"] = [
                    _strip_null_optionals(
                        ref, required_strings=_REQUIRED_STR_FIELDS["source_ref"]
                    )
                    for ref in op["source_refs"]
                    if isinstance(ref, Mapping)
                ]
            if "claims" in op:
                if not isinstance(op["claims"], list):
                    raise ValueError("claims must be a list")
                op["claims"] = [
                    _strip_null_optionals(
                        c, required_strings=_REQUIRED_STR_FIELDS["claim"]
                    )
                    for c in op["claims"]
                    if isinstance(c, Mapping)
                ]
            if "aliases" in op and isinstance(op["aliases"], list):
                op["aliases"] = [a for a in op["aliases"] if isinstance(a, str)]
            ops.append(op)
        cleaned["page_ops"] = ops

    if "lint_proposals" in cleaned:
        if not isinstance(cleaned["lint_proposals"], list):
            raise ValueError("lint_proposals must be a list")
        proposals = []
        for item in cleaned["lint_proposals"]:
            if not isinstance(item, Mapping):
                raise ValueError("lint_proposals entries must be objects")
            prop = _strip_null_optionals(
                item, required_strings=_REQUIRED_STR_FIELDS["lint_item"]
            )
            if isinstance(prop.get("proposal"), Mapping):
                prop["proposal"] = _strip_null_optionals(prop["proposal"])
            proposals.append(prop)
        cleaned["lint_proposals"] = proposals

    return WikiCompilePlan.from_dict(cleaned)


def parse_lint_report(raw: Mapping[str, Any]) -> WikiLintReport:
    """Deserialize a raw LLM JSON dict into a typed `WikiLintReport`."""
    cleaned = _strip_null_optionals(raw)
    if "issues" in cleaned:
        if not isinstance(cleaned["issues"], list):
            raise ValueError("issues must be a list")
        issues = []
        for item in cleaned["issues"]:
            if not isinstance(item, Mapping):
                raise ValueError("issues entries must be objects")
            issue = _strip_null_optionals(
                item, required_strings=_REQUIRED_STR_FIELDS["lint_item"]
            )
            if isinstance(issue.get("proposal"), Mapping):
                issue["proposal"] = _strip_null_optionals(issue["proposal"])
            issues.append(issue)
        cleaned["issues"] = issues
    return WikiLintReport.from_dict(cleaned)


def sanitize_xml_payload(text: str) -> str:
    """Neutralize prompt boundary tags (any case/whitespace) inside untrusted payloads."""
    return _BOUNDARY_TAG_RE.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def render_prompt_template(template: str, values: dict[str, str]) -> str:
    """Single-pass placeholder substitution preventing chained injection across fields."""
    return _PLACEHOLDER_RE.sub(
        lambda m: values[m.group(1)] if m.group(1) in values else m.group(0),
        template,
    )


_CANDIDATE_KIND_PRIORITY: dict[str, int] = {
    "project": 0,
    "entity": 1,
    "topic": 2,
    "source_digest": 3,
    "index": 4,
    "log": 5,
}
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "not",
        "but",
        "note",
        "notes",
        "page",
        "pages",
        "projects",
        "entities",
        "topics",
        "sources",
    }
)


def _extract_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def select_candidate_pages(
    all_pages: Sequence[WikiPageDTO],
    diff_payload: list[dict[str, Any]],
    linked_context: dict[str, Any],
    *,
    limit: int = 20,
) -> list[WikiPageDTO]:
    """Select the most relevant existing non-index/log pages for the incoming diff.

    Prioritizes pages that share a source `file_id`, match titles/aliases/tokens
    in the incoming notes or tasks, or sit 1 hop away via wikilinks—preventing
    recency-only truncation from clobbering older wiki pages during updates.
    """
    diff_file_ids: set[int] = set()
    corpus_parts: list[str] = []
    for ev in diff_payload:
        rfid = ev.get("related_file_id")
        if isinstance(rfid, int):
            diff_file_ids.add(rfid)
        payload = ev.get("payload")
        if isinstance(payload, Mapping):
            for key in ("file_path", "text_content", "previous_text"):
                val = payload.get(key)
                if isinstance(val, str) and val:
                    corpus_parts.append(val)
    for task in linked_context.get("tasks") or []:
        if isinstance(task, Mapping):
            for key in ("title", "detail"):
                val = task.get(key)
                if isinstance(val, str) and val:
                    corpus_parts.append(val)

    corpus_lower = "\n".join(corpus_parts).lower()
    corpus_tokens = _extract_tokens(corpus_lower)

    eligible = [p for p in all_pages if p.page_kind not in ("index", "log")]
    scores: dict[str, int] = {}
    for p in eligible:
        score = 0
        if diff_file_ids and any(ref.file_id in diff_file_ids for ref in p.source_refs):
            score += 100
        names = [p.title, *p.aliases]
        if corpus_lower and any(
            (norm := name.strip().lower())
            and re.search(rf"\b{re.escape(norm)}\b", corpus_lower)
            for name in names
        ):
            score += 40
        if corpus_tokens:
            page_tokens = _extract_tokens(
                f"{p.slug.replace('/', ' ')} {p.title} {' '.join(p.aliases)}"
            )
            score += 10 * len(page_tokens & corpus_tokens)
        scores[p.slug] = score

    # Boost 1-hop graph neighbors of directly matched pages (bidirectional).
    matched_slugs = {slug for slug, s in scores.items() if s > 0}
    if matched_slugs:
        neighbor_slugs: set[str] = set()
        for p in eligible:
            if p.slug in matched_slugs:
                neighbor_slugs.update(p.outbound_links)
                neighbor_slugs.update(p.backlinks)
        for p in eligible:
            if scores[p.slug] == 0 and (
                p.slug in neighbor_slugs
                or any(link in matched_slugs for link in p.outbound_links)
                or any(bl in matched_slugs for bl in p.backlinks)
            ):
                scores[p.slug] = 5

    ranked = sorted(
        eligible,
        key=lambda p: (
            -scores[p.slug],
            _CANDIDATE_KIND_PRIORITY.get(p.page_kind, 4),
            -p.update_time,
        ),
    )
    return ranked[: max(1, limit)]


def build_compile_prompt(
    all_pages: Sequence[WikiPageDTO],
    diff_payload: list[dict[str, Any]],
    linked_context: dict[str, Any],
    *,
    max_pages_per_batch: int = 5,
) -> str:
    """Render `PromptId.WIKI_COMPILE` with sanitized index, candidates, diff, and context."""
    compact_index = "\n".join(
        f"- [[{p.slug}]] ({p.page_kind}): {p.title} — {p.summary}"
        for p in all_pages
        if p.page_kind not in ("index", "log")
    )
    selected_candidates = select_candidate_pages(
        all_pages, diff_payload, linked_context, limit=20
    )
    candidate_pages = [
        {
            "slug": p.slug,
            "title": p.title,
            "page_kind": p.page_kind,
            "edit_policy": p.edit_policy,
            "version": p.version,
            "aliases": p.aliases,
            "body_md": p.body_md[:8000],
        }
        for p in selected_candidates
    ]
    template = PROMPT_LOADER.get_prompt(PromptId.WIKI_COMPILE)
    return render_prompt_template(
        template,
        {
            "max_pages_per_batch": str(max(1, max_pages_per_batch)),
            "compact_index_md": sanitize_xml_payload(compact_index),
            "candidate_pages_json": sanitize_xml_payload(json.dumps(candidate_pages)),
            "diff_events_json": sanitize_xml_payload(json.dumps(diff_payload)),
            "linked_note_and_task_context_json": sanitize_xml_payload(
                json.dumps(linked_context)
            ),
        },
    )


def build_lint_prompt(
    pages: Sequence[WikiPageDTO],
    tasks: Sequence[ScheduleTaskDO],
) -> str:
    """Render `PromptId.WIKI_LINT` with sanitized page summaries/claims and task snapshots."""
    pages_json = sanitize_xml_payload(
        json.dumps(
            [
                {
                    "slug": p.slug,
                    "title": p.title,
                    "summary": p.summary,
                    "aliases": p.aliases,
                    "claims": p.claims,
                }
                for p in pages
            ]
        )
    )
    tasks_json = sanitize_xml_payload(
        json.dumps(
            [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "status": t.status,
                    "due_time": t.due_time,
                }
                for t in tasks
            ]
        )
    )
    template = PROMPT_LOADER.get_prompt(PromptId.WIKI_LINT)
    return render_prompt_template(
        template,
        {
            "pages_batch_json": pages_json,
            "task_snapshots_json": tasks_json,
        },
    )
