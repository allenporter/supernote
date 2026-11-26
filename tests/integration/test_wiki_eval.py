"""Integration tests for the repeatable LLM Wiki backfill evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

from evals.wiki import (
    DeterministicFakeWikiModel,
    format_markdown_report,
    load_wiki_eval_dataset,
    run_wiki_eval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "evals/wiki/dataset.yaml"
DAILY_LOG_DATASET_PATH = REPO_ROOT / "evals/wiki/daily_log_dataset.yaml"


def test_wiki_eval_dataset_manifest_is_multi_batch_and_well_formed() -> None:
    dataset = load_wiki_eval_dataset(DATASET_PATH)
    assert dataset.name == "supernote-wiki-backfill-v1"
    transcribed = [nb for nb in dataset.notebooks if nb.pages]
    untranscribed = [nb for nb in dataset.notebooks if not nb.pages]
    total_pages = sum(len(nb.pages) for nb in transcribed)
    max_pages_in_notebook = max(len(nb.pages) for nb in transcribed)
    assert len(transcribed) >= 15
    assert len(untranscribed) >= 1
    assert total_pages >= 50
    assert max_pages_in_notebook >= 20
    assert len(dataset.tasks) >= 5
    assert len(dataset.expected_concepts) >= 6
    assert len(dataset.expected_facts) >= 4


async def test_run_wiki_eval_end_to_end_with_fake_model_and_vault_export(
    tmp_path: Path,
) -> None:
    dataset = load_wiki_eval_dataset(DATASET_PATH)
    export_dir = tmp_path / "wiki_eval_out"
    report = await run_wiki_eval(
        dataset,
        DeterministicFakeWikiModel(),
        max_files_per_batch=5,
        max_pages_per_batch=5,
        run_semantic_lint=True,
        export_dir=export_dir,
    )

    # 17 transcribed notebooks in batches of 5 -> 4 batches, plus deterministic `index` page.
    assert report.metrics.transcribed_notebooks == 17
    assert report.metrics.batches_run == 4
    assert report.metrics.total_pages == 18
    assert report.metrics.has_index_page is True
    assert report.metrics.pages_by_kind == {"index": 1, "source_digest": 17}
    # Index links must not mask disconnected orphan_page findings.
    assert report.metrics.open_lint_total == 17
    assert report.metrics.open_lint_by_type == {"orphan_page": 17}

    # Exported vault + reports exist and are readable.
    assert (export_dir / "report.json").is_file()
    assert (export_dir / "report.md").is_file()
    parsed = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
    assert parsed["dataset_name"] == dataset.name
    exported_md = list((export_dir / "vault").rglob("*.md"))
    assert len(exported_md) == 18

    md = format_markdown_report(report)
    assert "Wiki Backfill Eval Report" in md
    assert "Non-source synthesized pages" in md


def test_daily_log_eval_dataset_manifest_is_well_formed() -> None:
    dataset = load_wiki_eval_dataset(DAILY_LOG_DATASET_PATH)
    assert dataset.name == "supernote-wiki-daily-log-v1"
    file_names = {nb.file_name for nb in dataset.notebooks}
    assert {
        "Daily.note",
        "Monthly_Log_2026.note",
        "Monthly_Reflections_2026.note",
        "Q3_2026_Quarterly_Reflection.note",
    }.issubset(file_names)
    total_pages = sum(len(nb.pages) for nb in dataset.notebooks)
    assert total_pages >= 15
    daily_nb = next(nb for nb in dataset.notebooks if nb.file_name == "Daily.note")
    assert any(
        sum(
            1 for line in p.text_content.splitlines() if line.startswith(("10.", "11."))
        )
        >= 4
        for p in daily_nb.pages
    )
    assert len(dataset.expected_concepts) >= 8
    assert len(dataset.expected_facts) >= 6


async def test_run_daily_log_eval_with_fake_model(tmp_path: Path) -> None:
    dataset = load_wiki_eval_dataset(DAILY_LOG_DATASET_PATH)
    export_dir = tmp_path / "daily_log_eval_out"
    report = await run_wiki_eval(
        dataset,
        DeterministicFakeWikiModel(),
        max_files_per_batch=1,
        max_pages_per_batch=5,
        run_semantic_lint=False,
        export_dir=export_dir,
    )
    assert report.metrics.transcribed_notebooks == len(dataset.notebooks)
    assert report.metrics.batches_run == len(dataset.notebooks)
    assert report.metrics.has_index_page is True
    assert (export_dir / "report.md").is_file()
