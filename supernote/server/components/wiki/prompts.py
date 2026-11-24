"""Structured-output JSON schemas and prompt builders for the LLM Wiki compiler."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

from .models import WikiPageDTO

__all__ = [
    "WIKI_COMPILE_SCHEMA",
    "WIKI_LINT_SCHEMA",
    "build_compile_prompt",
    "build_lint_prompt",
    "render_prompt_template",
    "sanitize_xml_payload",
]

# JSON Schema passed to `TextGenerationModel.generate_json(response_schema=...)`
# for `PromptId.WIKI_COMPILE` (constrained decoding on Gemini / OpenAI).
# There is no standalone response dataclass: `WikiCompilerWorker._apply_compile_plan`
# validates and maps each `page_ops` entry into `WikiUpsertInput` + `WikiSourceRefDTO`,
# each `lint_proposals` entry into a `WikiLintIssueDO` row, and `log_entry` onto
# the `log` wiki page.
WIKI_COMPILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "page_kind": {"type": "string"},
                    "summary": {"type": "string"},
                    "body_md": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "source_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_type": {"type": "string"},
                                "source_key": {"type": "string"},
                                "file_id": {"type": ["integer", "null"]},
                            },
                            "required": ["source_type", "source_key"],
                        },
                    },
                    "change_summary": {"type": "string"},
                },
                "required": ["slug", "title", "body_md"],
            },
        },
        "lint_proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "description": {"type": "string"},
                    "proposal": {"type": "object"},
                },
                "required": ["issue_type", "description"],
            },
        },
        "log_entry": {"type": "string"},
    },
    "required": ["page_ops"],
}

# JSON Schema passed to `TextGenerationModel.generate_json(response_schema=...)`
# for `PromptId.WIKI_LINT`. `WikiCompilerWorker.run_semantic_lint` maps each
# `issues` entry into a `WikiLintIssueDO` row (without mutating wiki pages).
WIKI_LINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "severity": {"type": "string"},
                    "description": {"type": "string"},
                    "proposal": {"type": "object"},
                },
                "required": ["issue_type", "description"],
            },
        }
    },
    "required": ["issues"],
}

_BOUNDARY_TAG_RE = re.compile(
    r"<\s*(/?)\s*(source_diff|linked_context|user_index|candidate_pages|pages_batch|task_snapshots)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def sanitize_xml_payload(text: str) -> str:
    """Neutralize prompt boundary tags (any case/whitespace) inside untrusted payloads."""
    return _BOUNDARY_TAG_RE.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def render_prompt_template(template: str, values: dict[str, str]) -> str:
    """Single-pass placeholder substitution preventing chained injection across fields."""
    return _PLACEHOLDER_RE.sub(
        lambda m: values[m.group(1)] if m.group(1) in values else m.group(0),
        template,
    )


def build_compile_prompt(
    all_pages: Sequence[WikiPageDTO],
    diff_payload: list[dict[str, Any]],
    linked_context: dict[str, Any],
) -> str:
    """Render `PromptId.WIKI_COMPILE` with sanitized index, candidates, diff, and context."""
    compact_index = "\n".join(
        f"- [[{p.slug}]] ({p.page_kind}): {p.title} — {p.summary}" for p in all_pages
    )
    candidate_pages = [
        {
            "slug": p.slug,
            "title": p.title,
            "page_kind": p.page_kind,
            "edit_policy": p.edit_policy,
            "version": p.version,
            "aliases": p.aliases,
            "body_md": p.body_md[:2000],
        }
        for p in all_pages[:10]
    ]
    template = PROMPT_LOADER.get_prompt(PromptId.WIKI_COMPILE)
    return render_prompt_template(
        template,
        {
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
