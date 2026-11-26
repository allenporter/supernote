"""Tests for `supernote.server.components.wiki.prompts`."""

from __future__ import annotations

import json

import pytest

from supernote.models.wiki import WikiPageDTO, WikiSourceRefDTO
from supernote.server.components.wiki.prompts import (
    build_compile_prompt,
    get_compile_json_schema,
    get_lint_json_schema,
    parse_compile_plan,
    parse_lint_report,
    render_prompt_template,
    sanitize_xml_payload,
    select_candidate_pages,
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
    def _page(
        idx: int,
        kind: str,
        slug: str,
        update_time: int,
        *,
        aliases: list[str] | None = None,
        outbound_links: list[str] | None = None,
        source_refs: list[WikiSourceRefDTO] | None = None,
    ) -> WikiPageDTO:
        return WikiPageDTO(
            page_id=idx,
            slug=slug,
            title=slug.split("/")[-1].replace("-", " ").title(),
            page_kind=kind,
            summary="s",
            body_md="body",
            claims=[],
            edit_policy="auto",
            last_author_kind="compiler",
            version=1,
            create_time=update_time,
            update_time=update_time,
            aliases=aliases or [],
            outbound_links=outbound_links or [],
            source_refs=source_refs or [],
        )

    # 25 newer unrelated pages must not crowd out an older page relevant to the diff.
    pages = [
        _page(i, "project", f"projects/recent-{i}", 2000 + i) for i in range(1, 26)
    ] + [
        _page(100, "index", "index", 100),
        _page(
            101,
            "topic",
            "topics/garden",
            50,
            outbound_links=["topics/compost"],
        ),
        _page(102, "topic", "topics/compost", 40),
        _page(
            103,
            "project",
            "projects/aurora",
            30,
            source_refs=[
                WikiSourceRefDTO(
                    source_type="note_page", source_key="77:p1", file_id=77
                )
            ],
        ),
    ]
    diff = [
        {
            "related_file_id": 77,
            "payload": {
                "file_path": "Garden_Notes.note",
                "text_content": "Planted garlic in the garden bed.",
            },
        }
    ]
    selected = select_candidate_pages(pages, diff, {}, limit=5)
    selected_slugs = [p.slug for p in selected]
    # Exact file_id match (aurora), title mention (garden), and 1-hop neighbor (compost) are all kept;
    # index is excluded because the server maintains it deterministically.
    assert "projects/aurora" in selected_slugs
    assert "topics/garden" in selected_slugs
    assert "topics/compost" in selected_slugs
    assert "index" not in selected_slugs

    prompt = build_compile_prompt(pages, diff, {}, max_pages_per_batch=10)
    assert "up to 10 pages per batch" in prompt
    candidates_section = prompt.split("<candidate_pages>", maxsplit=1)[1].split(
        "</candidate_pages>", maxsplit=1
    )[0]
    assert '"slug": "projects/aurora"' in candidates_section
    assert '"slug": "topics/garden"' in candidates_section
    assert '"slug": "index"' not in candidates_section


def test_select_candidate_pages_uses_word_boundaries_for_short_names() -> None:
    def _entity(idx: int, slug: str, title: str, update_time: int) -> WikiPageDTO:
        return WikiPageDTO(
            page_id=idx,
            slug=slug,
            title=title,
            page_kind="entity",
            summary="",
            body_md="body",
            claims=[],
            edit_policy="auto",
            last_author_kind="compiler",
            version=1,
            create_time=update_time,
            update_time=update_time,
        )

    pages = [
        _entity(1, "entities/al", "Al", 10),
        _entity(2, "entities/maya", "Maya", 20),
        _entity(3, "entities/bob", "Bob", 30),
    ]
    # "also" contains "al" as a substring, but should NOT match entity "Al".
    diff_false = [
        {"payload": {"text_content": "We also talked with Maya about the final plan."}}
    ]
    ranked_false = [
        p.slug for p in select_candidate_pages(pages, diff_false, {}, limit=2)
    ]
    assert ranked_false[0] == "entities/maya"
    assert "entities/al" not in ranked_false

    # Standalone word "Al" SHOULD match entity "Al".
    diff_true = [{"payload": {"text_content": "Met with Al at noon."}}]
    ranked_true = [
        p.slug for p in select_candidate_pages(pages, diff_true, {}, limit=2)
    ]
    assert ranked_true[0] == "entities/al"
