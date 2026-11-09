"""Tests for `supernote.server.ai.eval`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.eval import (
    OcrEvalCase,
    OcrEvalDataset,
    OcrEvalSuiteReport,
    OcrEvalTarget,
    OcrTargetCaseResult,
    _summarize_results,
    _word_jaccard,
    build_target_report,
    compute_pareto_frontier,
    evaluate_ocr_dataset,
    format_markdown_report,
    load_eval_case_input,
    merge_eval_reports,
    render_pareto_svg,
    rescore_suite_report,
    score_ocr_output,
)
from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.ocr import OcrModel

REPO_ROOT = Path(__file__).resolve().parents[3]

BUJO_REFERENCE = (
    "2026-11-07 Friday\n"
    "* • Review Q4 budget\n"
    "X Send lease renewal\n"
    "  - Agreed on local OCR\n"
    "• ~~Order nibs~~\n"
    "• ---\n"
)


class _ScriptedOcrModel(OcrModel):
    def __init__(
        self,
        responses: list[str | AIError],
        model_id: str = "scripted-ocr-v1",
    ) -> None:
        self._responses = list(responses)
        self._model_id = model_id
        self.calls = 0

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return self._model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        item = self._responses[idx]
        if isinstance(item, AIError):
            raise item
        return item


@pytest.fixture
def sample_png_dir(tmp_path: Path) -> Path:
    (tmp_path / "sample.png").write_bytes(b"pngdata")
    return tmp_path


@pytest.fixture
def mixed_eval_dataset() -> OcrEvalDataset:
    return OcrEvalDataset(
        name="unit-suite",
        cases=[
            OcrEvalCase(
                id="p1",
                path="sample.png",
                category="bujo_daily",
                prompt_type="daily",
                ground_truth="* • Task one",
            ),
            OcrEvalCase(
                id="rtr1",
                path=str(REPO_ROOT / "tests/testdata/philips/a5x-2.14.28.note"),
                category="english_prose",
                ground_truth="Subject: Obsidian Supernote Integration",
            ),
        ],
    )


@pytest.fixture
def png_only_dataset() -> OcrEvalDataset:
    return OcrEvalDataset(
        cases=[OcrEvalCase(id="only_png", path="sample.png", ground_truth="hi")]
    )


@pytest.mark.parametrize(
    ("case_id", "path", "page_index", "error_match"),
    [
        ("  ", "a.png", 0, "id must be non-empty"),
        ("c1", "", 0, "path must be non-empty"),
        ("c1", "a.note", -1, "page_index must be >= 0"),
    ],
)
def test_eval_case_validation(
    case_id: str, path: str, page_index: int, error_match: str
) -> None:
    with pytest.raises(ValueError, match=error_match):
        OcrEvalCase(id=case_id, path=path, page_index=page_index)


def test_eval_dataset_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="Duplicate OcrEvalCase id"):
        OcrEvalDataset(
            cases=[
                OcrEvalCase(id="dup", path="a.png"),
                OcrEvalCase(id="dup", path="b.png"),
            ]
        )


def test_eval_dataset_load_yaml(tmp_path: Path) -> None:
    manifest = tmp_path / "dataset.yaml"
    manifest.write_text(
        "---\nname: mini\ncases:\n  - id: c1\n    path: page.png\n    ground_truth: hi\n",
        encoding="utf-8",
    )
    loaded = OcrEvalDataset.load(manifest)
    assert loaded.name == "mini"
    assert len(loaded.cases) == 1
    assert loaded.cases[0].id == "c1"


def test_checked_in_ocr_dataset_manifest_assets_exist() -> None:
    manifest_path = REPO_ROOT / "evals/ocr/dataset.yaml"
    dataset = OcrEvalDataset.load(manifest_path)
    assert len(dataset.cases) >= 20
    for case in dataset.cases:
        asset = (manifest_path.parent / case.path).resolve()
        assert asset.exists(), f"Missing asset for {case.id}: {asset}"


def test_checked_in_ocr_results_match_markdown_report() -> None:
    dataset = OcrEvalDataset.load(REPO_ROOT / "evals/ocr/dataset.yaml")
    results_dir = REPO_ROOT / "evals/ocr/results"
    json_files = sorted(results_dir.glob("*.json"))
    assert len(json_files) >= 2
    reports = [
        OcrEvalSuiteReport.from_json(path.read_text(encoding="utf-8"))
        for path in json_files
    ]
    merged = merge_eval_reports(reports)
    assert merged.dataset_name == dataset.name
    results_md = (REPO_ROOT / "evals/ocr/RESULTS.md").read_text(encoding="utf-8")
    assert results_md == format_markdown_report(merged)
    pareto_svg = (REPO_ROOT / "evals/ocr/pareto_frontier.svg").read_text(
        encoding="utf-8"
    )
    assert pareto_svg == render_pareto_svg(merged)


def test_score_ocr_output_empty_reference() -> None:
    empty_ok = score_ocr_output("", "   ")
    assert empty_ok.cer == 0.0
    assert empty_ok.word_recall == 1.0
    assert empty_ok.bujo_symbol_recall is None


def test_score_ocr_output_empty_reference_hallucination() -> None:
    empty_hallucination = score_ocr_output("", "phantom dots")
    assert empty_hallucination.cer == 1.0
    assert empty_hallucination.word_recall == 0.0


def test_score_ocr_output_shorter_reference_than_hypothesis() -> None:
    short_vs_long = score_ocr_output("hi", "hi there friend")
    assert short_vs_long.cer > 1.0
    assert short_vs_long.word_recall == 1.0


def test_score_ocr_output_punctuation_only_and_empty_jaccard() -> None:
    punct_only = score_ocr_output("... !", "... !")
    assert punct_only.cer == 0.0
    assert punct_only.word_recall == 1.0
    assert _word_jaccard(frozenset(), frozenset()) == 0.0


def test_score_ocr_output_bujo_perfect_match() -> None:
    perfect_hyp = (
        "2026-11-07 Friday\n"
        "* • Review Q4 budget\n"
        "X Send lease renewal\n"
        "  - Agreed on local OCR\n"
        "• ~~Order nibs~~\n"
    )
    perfect = score_ocr_output(BUJO_REFERENCE, perfect_hyp)
    assert perfect.bujo_expected_items == 4
    assert perfect.bujo_symbol_recall == 1.0
    assert perfect.bujo_strikethrough_recall == 1.0
    assert perfect.bujo_indent_accuracy == 1.0
    assert perfect.content_cer < 0.05


def test_score_ocr_output_bujo_partial_without_symbols() -> None:
    unformatted_hyp = (
        "2026-11-07 Friday\n"
        "Review Q4 budget\n"
        "X Send lease renewal\n"
        "Agreed on local OCR\n"
        "Order nibs\n"
        "unrelated extra line\n"
    )
    partial = score_ocr_output(BUJO_REFERENCE, unformatted_hyp)
    assert partial.bujo_expected_items == 4
    assert partial.bujo_symbol_recall == 0.25
    assert partial.bujo_strikethrough_recall == 0.0
    assert partial.bujo_indent_accuracy == 0.0
    assert partial.content_cer < partial.cer


def test_score_ocr_output_bujo_empty_hypothesis() -> None:
    empty_hyp = score_ocr_output(BUJO_REFERENCE, "")
    assert empty_hyp.bujo_symbol_recall == 0.0
    assert empty_hyp.wer == 1.0


def test_load_eval_case_input_png(tmp_path: Path) -> None:
    png_file = tmp_path / "daily.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    png_page = load_eval_case_input(
        OcrEvalCase(id="png1", path="daily.png", ground_truth="hello"),
        tmp_path,
    )
    assert png_page.png_data == b"\x89PNG\r\n\x1a\nfake"
    assert png_page.device_rtr_text is None
    assert "Daily Log" in png_page.prompt


def test_load_eval_case_input_note_with_device_rtr() -> None:
    rtr_note_case = OcrEvalCase(
        id="a5x",
        path="tests/testdata/philips/a5x-2.14.28.note",
        page_index=0,
        ground_truth="Subject",
    )
    loaded_note = load_eval_case_input(rtr_note_case, REPO_ROOT)
    assert loaded_note.png_data.startswith(b"\x89PNG")
    assert loaded_note.device_rtr_text is not None
    assert "Obsidian" in loaded_note.device_rtr_text


def test_load_eval_case_input_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        load_eval_case_input(OcrEvalCase(id="missing", path="nope.png"), tmp_path)


def test_load_eval_case_input_page_index_out_of_range() -> None:
    with pytest.raises(IndexError, match="out of range"):
        load_eval_case_input(
            OcrEvalCase(
                id="oob",
                path="tests/testdata/philips/manta.note",
                page_index=5,
            ),
            REPO_ROOT,
        )


def test_load_eval_case_input_unsupported_extension(tmp_path: Path) -> None:
    txt_file = tmp_path / "bad.txt"
    txt_file.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported asset extension"):
        load_eval_case_input(OcrEvalCase(id="bad", path="bad.txt"), tmp_path)


def test_summarize_results_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty result sequence"):
        _summarize_results("all", [])


async def test_evaluate_ocr_dataset_empty_cases_raises(tmp_path: Path) -> None:
    empty_ds = OcrEvalDataset(cases=[])
    with pytest.raises(ValueError, match="at least one case"):
        await evaluate_ocr_dataset(
            empty_ds, tmp_path, [OcrEvalTarget("f", FakeOcrModel())]
        )


async def test_evaluate_ocr_dataset_no_targets_raises(
    sample_png_dir: Path,
    mixed_eval_dataset: OcrEvalDataset,
) -> None:
    with pytest.raises(ValueError, match="At least one OcrEvalTarget"):
        await evaluate_ocr_dataset(
            mixed_eval_dataset, sample_png_dir, [], include_device_rtr=False
        )


async def test_evaluate_ocr_dataset_and_markdown_report(
    sample_png_dir: Path,
    mixed_eval_dataset: OcrEvalDataset,
) -> None:
    flaky_model = _ScriptedOcrModel(
        [
            AIError("warmup hiccup"),
            "* • Task one",
            AIError("timeout on page 2"),
        ]
    )
    report = await evaluate_ocr_dataset(
        mixed_eval_dataset,
        sample_png_dir,
        [
            OcrEvalTarget("fake:v1", FakeOcrModel("fake-v1")),
            OcrEvalTarget("flaky:v1", flaky_model),
        ],
        warmup=True,
        include_device_rtr=True,
        fail_fast=False,
    )
    assert report.case_count == 2
    assert [t.target_name for t in report.targets] == [
        "fake:v1",
        "flaky:v1",
        "device-rtr",
    ]
    assert report.targets[1].overall.error_count == 1

    md = format_markdown_report(report)
    assert "`fake:v1`" in md
    assert "`device-rtr`" in md
    assert "`bujo_daily`" in md


async def test_evaluate_ocr_dataset_skips_device_rtr_when_absent(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    report = await evaluate_ocr_dataset(
        png_only_dataset,
        sample_png_dir,
        [OcrEvalTarget("fake:v1", FakeOcrModel())],
        warmup=False,
        include_device_rtr=True,
    )
    assert [t.target_name for t in report.targets] == ["fake:v1"]


async def test_evaluate_ocr_dataset_fail_fast_during_warmup(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    with pytest.raises(AIError, match="boom warmup"):
        await evaluate_ocr_dataset(
            png_only_dataset,
            sample_png_dir,
            [OcrEvalTarget("err", _ScriptedOcrModel([AIError("boom warmup")]))],
            warmup=True,
            fail_fast=True,
        )


async def test_evaluate_ocr_dataset_fail_fast_during_page_inference(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    with pytest.raises(AIError, match="boom page"):
        await evaluate_ocr_dataset(
            png_only_dataset,
            sample_png_dir,
            [OcrEvalTarget("err", _ScriptedOcrModel([AIError("boom page")]))],
            warmup=False,
            fail_fast=True,
        )


def test_merge_eval_reports_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one report"):
        merge_eval_reports([])


def test_merge_eval_reports_mismatched_dataset_raises() -> None:
    report_a = OcrEvalSuiteReport(dataset_name="suite-a", case_count=1, targets=[])
    report_b = OcrEvalSuiteReport(dataset_name="suite-b", case_count=1, targets=[])
    with pytest.raises(ValueError, match="different datasets"):
        merge_eval_reports([report_a, report_b])


async def test_merge_eval_reports_replaces_existing_targets_in_order(
    sample_png_dir: Path,
    mixed_eval_dataset: OcrEvalDataset,
) -> None:
    initial = await evaluate_ocr_dataset(
        mixed_eval_dataset,
        sample_png_dir,
        [
            OcrEvalTarget("fake:v1", FakeOcrModel("fake-v1")),
            OcrEvalTarget("other:v1", FakeOcrModel("other-v1")),
        ],
        warmup=False,
        include_device_rtr=True,
    )
    updated = await evaluate_ocr_dataset(
        mixed_eval_dataset,
        sample_png_dir,
        [
            OcrEvalTarget("fake:v1", FakeOcrModel("fake-v1-updated")),
            OcrEvalTarget("new:v1", FakeOcrModel("new-v1")),
        ],
        warmup=False,
    )

    merged = merge_eval_reports([initial, updated])
    assert [t.target_name for t in merged.targets] == [
        "fake:v1",
        "other:v1",
        "device-rtr",
        "new:v1",
    ]
    assert merged.targets[0].model_id == "fake-v1-updated"


def test_eval_case_preserves_optional_language() -> None:
    turkish_loaded = load_eval_case_input(
        OcrEvalCase(
            id="tr0",
            path="tests/testdata/philips/turkish.note",
            page_index=0,
            language="tr_TR",
            ground_truth="Şimdi",
        ),
        REPO_ROOT,
    )
    assert turkish_loaded.case.language == "tr_TR"


def test_build_target_report_aggregates_external_results() -> None:
    target = build_target_report(
        target_name="supernote-on-device",
        model_id="myscript-iink-4.1.0",
        warmup_ms=0.0,
        case_results=[
            OcrTargetCaseResult(
                case_id="c1",
                category="english_prose",
                hypothesis="hello world",
                latency_ms=120.0,
                metrics=score_ocr_output("hello world", "hello world"),
            )
        ],
    )
    assert target.target_name == "supernote-on-device"
    assert target.overall.mean_cer == 0.0
    assert target.overall.median_latency_ms == 120.0
    assert [c.category for c in target.by_category] == ["english_prose"]


class _SlowOcrModel(OcrModel):
    @property
    def provider(self) -> str:
        return "slow"

    @property
    def model_id(self) -> str:
        return "slow-ocr-v1"

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        await asyncio.sleep(0.2)
        return "too late"


async def test_evaluate_ocr_dataset_page_timeout_records_error(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    report = await evaluate_ocr_dataset(
        png_only_dataset,
        sample_png_dir,
        [OcrEvalTarget("slow:v1", _SlowOcrModel())],
        warmup=False,
        page_timeout_s=0.01,
    )
    assert report.targets[0].overall.error_count == 1
    assert report.targets[0].cases[0].error == "Timed out after 0.0s"


def test_eval_case_is_bujo() -> None:
    assert OcrEvalCase(id="b1", path="a.png", category="bujo_daily").is_bujo
    assert OcrEvalCase(id="b2", path="a.png", prompt_type="weekly").is_bujo
    assert not OcrEvalCase(id="p1", path="a.png", category="multilingual").is_bujo


def test_score_ocr_output_multiset_word_recall_and_contractions() -> None:
    metrics = score_ocr_output("I L's C C C", "I Ls C extra")
    assert metrics.word_recall == 0.6
    assert metrics.word_f1 == 0.6667


def test_score_ocr_output_case_insensitive_content_cer() -> None:
    metrics = score_ocr_output("Salad Lesson", "salad lesson")
    assert metrics.cer > 0.0
    assert metrics.content_cer == 0.0


def test_score_ocr_output_skips_bujo_on_non_bujo_prose_dashes() -> None:
    prose = "- I want to celebrate\n- Quiero celebrar"
    metrics = score_ocr_output(prose, prose, evaluate_bujo=False)
    assert metrics.bujo_expected_items == 0
    assert metrics.bujo_symbol_recall is None


async def test_rescore_suite_report_updates_metrics_and_categories(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    report = await evaluate_ocr_dataset(
        png_only_dataset,
        sample_png_dir,
        [
            OcrEvalTarget("ok:v1", _ScriptedOcrModel(["HI"])),
            OcrEvalTarget("err:v1", _ScriptedOcrModel([AIError("failed")])),
        ],
        warmup=False,
    )
    updated_ds = OcrEvalDataset(
        name="rescored-suite",
        cases=[
            OcrEvalCase(
                id="only_png",
                path="sample.png",
                category="english_prose",
                ground_truth="hi",
            )
        ],
    )
    rescored = rescore_suite_report(report, updated_ds)
    assert rescored.dataset_name == "rescored-suite"
    assert rescored.targets[0].cases[0].category == "english_prose"
    assert rescored.targets[0].cases[0].metrics.content_cer == 0.0
    assert rescored.targets[0].cases[0].metrics.word_f1 == 1.0
    assert rescored.targets[1].cases[0].metrics.word_f1 == 0.0


async def test_rescore_suite_report_missing_case_raises(
    sample_png_dir: Path,
    png_only_dataset: OcrEvalDataset,
) -> None:
    report = await evaluate_ocr_dataset(
        png_only_dataset,
        sample_png_dir,
        [OcrEvalTarget("ok:v1", FakeOcrModel())],
        warmup=False,
    )
    other_ds = OcrEvalDataset(cases=[OcrEvalCase(id="other", path="sample.png")])
    with pytest.raises(KeyError, match="not found in dataset"):
        rescore_suite_report(report, other_ds)


def test_compute_pareto_frontier_identifies_dominated_targets() -> None:
    fast_low = build_target_report(
        "fast:v1",
        "m1",
        0.0,
        [
            OcrTargetCaseResult(
                case_id="c1",
                category="english_prose",
                hypothesis="a",
                latency_ms=100.0,
                metrics=score_ocr_output("a b", "a"),
            )
        ],
    )
    mid_high = build_target_report(
        "mid:v1",
        "m2",
        0.0,
        [
            OcrTargetCaseResult(
                case_id="c1",
                category="english_prose",
                hypothesis="a b",
                latency_ms=400.0,
                metrics=score_ocr_output("a b", "a b"),
            )
        ],
    )
    slow_dominated = build_target_report(
        "slow:v1",
        "m3",
        0.0,
        [
            OcrTargetCaseResult(
                case_id="c1",
                category="english_prose",
                hypothesis="a",
                latency_ms=900.0,
                metrics=score_ocr_output("a b", "a"),
            )
        ],
    )
    zero_lat = build_target_report(
        "device-rtr",
        "rtr",
        0.0,
        [
            OcrTargetCaseResult(
                case_id="c1",
                category="english_prose",
                hypothesis="a b",
                latency_ms=0.0,
                metrics=score_ocr_output("a b", "a b"),
            )
        ],
    )
    suite = OcrEvalSuiteReport(
        dataset_name="pareto-suite",
        case_count=1,
        targets=[slow_dominated, zero_lat, fast_low, mid_high],
    )
    pts = compute_pareto_frontier(suite, use_p95_latency=True)
    assert [(p.target_name, p.is_pareto) for p in pts] == [
        ("fast:v1", True),
        ("mid:v1", True),
        ("slow:v1", False),
    ]
    svg = render_pareto_svg(suite)
    assert "<svg" in svg
    assert "fast:v1" in svg


def test_render_pareto_svg_formats_known_provider_labels() -> None:
    targets = [
        build_target_report(
            target_name,
            target_name,
            0.0,
            [
                OcrTargetCaseResult(
                    case_id="c1",
                    category="english_prose",
                    hypothesis="hello",
                    latency_ms=lat,
                    metrics=score_ocr_output("hello", "hello"),
                )
            ],
        )
        for target_name, lat in (
            ("apple:vision-fast", 120.0),
            ("apple:vision-accurate", 400.0),
            ("supernote-on-device", 900.0),
            ("gemini:gemini-3.5-flash-lite", 1200.0),
            ("gemini:gemini-3.6-flash", 6500.0),
        )
    ]
    svg = render_pareto_svg(
        OcrEvalSuiteReport(dataset_name="suite", case_count=1, targets=targets)
    )
    assert "Apple Vision Fast (100.0%)" in svg
    assert "Apple Vision Accurate (100.0%)" in svg
    assert "Supernote On-Device (100.0%)" in svg
    assert "Gemini 3.5 Flash-Lite (100.0%)" in svg
    assert "Gemini 3.6 Flash (100.0%)" in svg
    assert "apple:vision-fast" not in svg
    assert "gemini:gemini-3.5-flash-lite" not in svg
