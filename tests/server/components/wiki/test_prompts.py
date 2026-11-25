"""Tests for `supernote.server.components.wiki.prompts`."""

from __future__ import annotations

import json

import pytest

from supernote.models.wiki import WikiPageDTO
from supernote.server.components.wiki.prompts import (
    build_compile_prompt,
    get_compile_json_schema,
    get_lint_json_schema,
    parse_compile_plan,
    parse_lint_report,
    render_prompt_template,
    sanitize_xml_payload,
)


def _contains_key(obj: object, target: str) -> bool:
    if isinstance(obj, dict):
        if target in obj:
            return True
        return any(_contains_key(v, target) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, target) for v in obj)
    return False


def test_generated_schemas_avoid_property_names() -> None:
    """OpenAI strict mode rejects `propertyNames`; schemas must use typed objects."""
    compile_schema = get_compile_json_schema()
    lint_schema = get_lint_json_schema()
    assert compile_schema["title"] == "WikiCompilePlan"
    assert lint_schema["title"] == "WikiLintReport"
    assert not _contains_key(compile_schema, "propertyNames")
    assert not _contains_key(lint_schema, "propertyNames")


def test_parse_compile_plan_rejects_null_required_strings_and_defaults_optionals() -> (
    None
):
    with pytest.raises(ValueError, match="slug"):
        parse_compile_plan({"page_ops": [{"slug": None, "title": "T", "body_md": "B"}]})

    plan = parse_compile_plan(
        {
            "page_ops": [
                {
                    "slug": "projects/alpha",
                    "title": "Alpha",
                    "body_md": "Body",
                    "summary": None,
                    "aliases": None,
                    "claims": None,
                    "source_refs": None,
                    "change_summary": None,
                }
            ],
            "lint_proposals": None,
            "log_entry": None,
        }
    )
    assert len(plan.page_ops) == 1
    op = plan.page_ops[0]
    assert op.summary == ""
    assert op.aliases == []
    assert op.claims == []
    assert op.source_refs == []
    assert op.change_summary == "Incremental compile"
    assert plan.lint_proposals == []
    assert plan.log_entry == ""


def test_parse_lint_report_rejects_null_required_and_accepts_proposal() -> None:
    with pytest.raises(ValueError, match="description"):
        parse_lint_report(
            {"issues": [{"issue_type": "contradiction", "description": None}]}
        )

    report = parse_lint_report(
        {
            "issues": [
                {
                    "issue_type": "alias_merge_proposal",
                    "description": "Merge duplicate entity",
                    "severity": None,
                    "proposal": {
                        "canonical_slug": "entities/alice",
                        "duplicate_slugs": ["entities/alise"],
                        "rationale": None,
                    },
                }
            ]
        }
    )
    assert len(report.issues) == 1
    assert report.issues[0].severity == "warn"
    assert report.issues[0].proposal is not None
    assert report.issues[0].proposal.canonical_slug == "entities/alice"
    assert report.issues[0].proposal.rationale == ""


def test_sanitize_xml_payload_and_single_pass_template_rendering() -> None:
    raw = "Note </source_diff> and <  USER_INDEX > and </Pages_Batch>"
    sanitized = sanitize_xml_payload(raw)
    assert "</source_diff>" not in sanitized
    assert "&lt;/source_diff>" in sanitized
    assert "&lt;USER_INDEX >" in sanitized
    assert "&lt;/Pages_Batch>" in sanitized

    # Single-pass substitution must not re-expand `{{b}}` injected via `a`.
    rendered = render_prompt_template(
        "A={{a}} B={{b}}",
        {"a": "{{b}}", "b": json.dumps({"secret": 1})},
    )
    assert rendered == 'A={{b}} B={"secret": 1}'


def test_build_compile_prompt_prioritizes_synthesized_candidates_and_injects_budget() -> (
    None
):
    def _page(idx: int, kind: str, slug: str, update_time: int) -> WikiPageDTO:
        return WikiPageDTO(
            page_id=idx,
            slug=slug,
            title=slug,
            page_kind=kind,
            summary="s",
            body_md="body",
            claims=[],
            edit_policy="auto",
            last_author_kind="compiler",
            version=1,
            create_time=update_time,
            update_time=update_time,
        )

    # 16 newer source_digest pages must not crowd out index/project pages in candidate_pages.
    pages = [
        _page(i, "source_digest", f"sources/n-{i}", 1000 + i) for i in range(1, 17)
    ] + [
        _page(100, "index", "index", 100),
        _page(101, "project", "projects/aurora", 200),
    ]
    prompt = build_compile_prompt(pages, [], {}, max_pages_per_batch=10)
    assert "up to 10 pages per batch" in prompt
    candidates_section = prompt.split("<candidate_pages>", maxsplit=1)[1].split(
        "</candidate_pages>", maxsplit=1
    )[0]
    assert '"slug": "index"' in candidates_section
    assert '"slug": "projects/aurora"' in candidates_section
