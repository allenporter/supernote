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

    # 17 transcribed notebooks in batches of 5 -> 4 batches.
    assert report.metrics.transcribed_notebooks == 17
    assert report.metrics.batches_run == 4
    assert report.metrics.total_pages == 17
    # Deterministic fake emits source_digest only, demonstrating the baseline ratio metric.
    assert report.metrics.non_source_pages == 0
    assert report.metrics.non_source_ratio == 0.0
    assert report.metrics.has_index_page is False
    assert report.metrics.open_lint_total > 0

    # Exported vault + reports exist and are readable.
    assert (export_dir / "report.json").is_file()
    assert (export_dir / "report.md").is_file()
    parsed = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
    assert parsed["dataset_name"] == dataset.name
    exported_md = list((export_dir / "vault").rglob("*.md"))
    assert len(exported_md) == 17

    md = format_markdown_report(report)
    assert "Wiki Backfill Eval Report" in md
    assert "Non-source synthesized pages" in md
