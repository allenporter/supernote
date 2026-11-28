"""Integration tests for the repeatable large-notebook summarization eval harness."""

from __future__ import annotations

import json
from pathlib import Path

from evals.summary import (
    DeterministicFakeSummaryModel,
    format_markdown_report,
    load_summary_eval_dataset,
    run_summary_eval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "evals/summary/dataset.yaml"


def test_summary_eval_dataset_manifest_is_well_formed() -> None:
    dataset = load_summary_eval_dataset(DATASET_PATH)
    assert dataset.name == "supernote-summary-large-notebooks-v1"
    assert len(dataset.notebooks) == 3
    total_pages = sum(len(nb.pages) for nb in dataset.notebooks)
    assert total_pages == 76
    total_facts = sum(len(nb.expected_facts) for nb in dataset.notebooks)
    assert total_facts == 30
    regions = {fact.region for nb in dataset.notebooks for fact in nb.expected_facts}
    assert {"early", "middle", "late", "boundary_continuation"} <= regions
    daily = next(nb for nb in dataset.notebooks if nb.file_name == "Daily_2026.note")
    assert daily.incremental_updates is not None
    assert daily.incremental_updates.append is not None
    assert daily.incremental_updates.mid_edit is not None


async def test_run_summary_eval_end_to_end_with_fake_model_and_export(
    tmp_path: Path,
) -> None:
    dataset = load_summary_eval_dataset(DATASET_PATH)
    export_dir = tmp_path / "summary_eval_out"
    report = await run_summary_eval(
        dataset,
        DeterministicFakeSummaryModel(),
        target_label="fake:deterministic",
        export_dir=export_dir,
    )
    assert len(report.notebooks) == 3
    assert report.overall_fact_recall == 1.0
    assert report.overall_date_accuracy == 1.0
    assert report.overall_page_ref_accuracy == 1.0
    assert (export_dir / "report.md").exists()
    assert (export_dir / "report.json").exists()
    assert (export_dir / "Daily_2026.summary.md").exists()

    parsed = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
    assert parsed["dataset_name"] == "supernote-summary-large-notebooks-v1"
    md = format_markdown_report(report)
    assert "Incremental Update Telemetry" in md
