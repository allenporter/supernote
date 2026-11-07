"""Tests for `supernote.server.ai.eval`."""

from __future__ import annotations

from pathlib import Path

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.eval import (
    OcrEvalCase,
    OcrEvalDataset,
    OcrEvalTarget,
    _summarize_results,
    _word_jaccard,
    evaluate_ocr_dataset,
    format_markdown_report,
    load_eval_case_input,
    score_ocr_output,
)
from supernote.server.ai.models.fake.ocr import FakeOcrModel
from supernote.server.ai.models.ocr import OcrModel

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    def model_id(self) -> str:
        return self._model_id

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        item = self._responses[idx]
        if isinstance(item, AIError):
            raise item
        return item


def test_eval_case_and_dataset_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="id must be non-empty"):
        OcrEvalCase(id="  ", path="a.png")
    with pytest.raises(ValueError, match="path must be non-empty"):
        OcrEvalCase(id="c1", path="")
    with pytest.raises(ValueError, match="page_index must be >= 0"):
        OcrEvalCase(id="c1", path="a.note", page_index=-1)

    with pytest.raises(ValueError, match="Duplicate OcrEvalCase id"):
        OcrEvalDataset(
            cases=[
                OcrEvalCase(id="dup", path="a.png"),
                OcrEvalCase(id="dup", path="b.png"),
            ]
        )

    manifest = tmp_path / "dataset.yaml"
    manifest.write_text(
        "---\nname: mini\ncases:\n  - id: c1\n    path: page.png\n    ground_truth: hi\n",
        encoding="utf-8",
    )
    loaded = OcrEvalDataset.load(manifest)
    assert loaded.name == "mini"
    assert len(loaded.cases) == 1
    assert loaded.cases[0].id == "c1"


def test_checked_in_ocr_dataset_manifest_is_valid() -> None:
    manifest_path = REPO_ROOT / "evals/ocr/dataset.yaml"
    dataset = OcrEvalDataset.load(manifest_path)
    assert len(dataset.cases) >= 20
    for case in dataset.cases:
        asset = (manifest_path.parent / case.path).resolve()
        assert asset.exists(), f"Missing asset for {case.id}: {asset}"


def test_score_ocr_output_empty_and_prose() -> None:
    empty_ok = score_ocr_output("", "   ")
    assert empty_ok.cer == 0.0
    assert empty_ok.word_recall == 1.0
    assert empty_ok.bujo_symbol_recall is None

    empty_hallucination = score_ocr_output("", "phantom dots")
    assert empty_hallucination.cer == 1.0
    assert empty_hallucination.word_recall == 0.0

    # Shorter reference than hypothesis exercises _levenshtein swap branch
    short_vs_long = score_ocr_output("hi", "hi there friend")
    assert short_vs_long.cer > 1.0
    assert short_vs_long.word_recall == 1.0

    # Punctuation-only reference exercises empty ref_content / ref_tokens fallbacks
    punct_only = score_ocr_output("... !", "... !")
    assert punct_only.cer == 0.0
    assert punct_only.word_recall == 1.0

    assert _word_jaccard(frozenset(), frozenset()) == 0.0


def test_score_ocr_output_bujo_rapid_logging() -> None:
    reference = (
        "2026-11-07 Friday\n"
        "* • Review Q4 budget\n"
        "X Send lease renewal\n"
        "  - Agreed on local OCR\n"
        "• ~~Order nibs~~\n"
        "• ---\n"
    )
    perfect_hyp = (
        "2026-11-07 Friday\n"
        "* • Review Q4 budget\n"
        "X Send lease renewal\n"
        "  - Agreed on local OCR\n"
        "• ~~Order nibs~~\n"
    )
    perfect = score_ocr_output(reference, perfect_hyp)
    assert perfect.bujo_expected_items == 4
    assert perfect.bujo_symbol_recall == 1.0
    assert perfect.bujo_strikethrough_recall == 1.0
    assert perfect.bujo_indent_accuracy == 1.0
    assert perfect.content_cer < 0.05

    # Plain optical OCR without Rapid Logging symbols still gets strong content_cer
    unformatted_hyp = (
        "2026-11-07 Friday\n"
        "Review Q4 budget\n"
        "X Send lease renewal\n"
        "Agreed on local OCR\n"
        "Order nibs\n"
        "unrelated extra line\n"
    )
    partial = score_ocr_output(reference, unformatted_hyp)
    assert partial.bujo_expected_items == 4
    assert partial.bujo_symbol_recall == 0.25  # Only 'X Send lease renewal' kept marker
    assert partial.bujo_strikethrough_recall == 0.0
    assert partial.bujo_indent_accuracy == 0.0
    assert partial.content_cer < partial.cer

    # Completely missing hypothesis
    empty_hyp = score_ocr_output(reference, "")
    assert empty_hyp.bujo_symbol_recall == 0.0
    assert empty_hyp.wer == 1.0


def test_load_eval_case_input_note_png_and_errors(tmp_path: Path) -> None:
    png_file = tmp_path / "daily.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    png_page = load_eval_case_input(
        OcrEvalCase(id="png1", path="daily.png", ground_truth="hello"),
        tmp_path,
    )
    assert png_page.png_data == b"\x89PNG\r\n\x1a\nfake"
    assert png_page.device_rtr_text is None
    assert "Daily Log" in png_page.prompt

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

    with pytest.raises(FileNotFoundError, match="not found"):
        load_eval_case_input(OcrEvalCase(id="missing", path="nope.png"), tmp_path)

    with pytest.raises(IndexError, match="out of range"):
        load_eval_case_input(
            OcrEvalCase(
                id="oob",
                path="tests/testdata/philips/manta.note",
                page_index=5,
            ),
            REPO_ROOT,
        )

    txt_file = tmp_path / "bad.txt"
    txt_file.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported asset extension"):
        load_eval_case_input(OcrEvalCase(id="bad", path="bad.txt"), tmp_path)


async def test_evaluate_ocr_dataset_and_markdown_report(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty result sequence"):
        _summarize_results("all", [])

    empty_ds = OcrEvalDataset(cases=[])
    with pytest.raises(ValueError, match="at least one case"):
        await evaluate_ocr_dataset(
            empty_ds, tmp_path, [OcrEvalTarget("f", FakeOcrModel())]
        )

    png_path = tmp_path / "sample.png"
    png_path.write_bytes(b"pngdata")
    png_ds = OcrEvalDataset(
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

    with pytest.raises(ValueError, match="At least one OcrEvalTarget"):
        await evaluate_ocr_dataset(png_ds, tmp_path, [], include_device_rtr=False)

    flaky_model = _ScriptedOcrModel(
        [
            AIError("warmup hiccup"),
            "* • Task one",
            AIError("timeout on page 2"),
        ]
    )
    report = await evaluate_ocr_dataset(
        png_ds,
        tmp_path,
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

    # Without RTR pages in dataset, include_device_rtr=True cleanly skips device-rtr target
    png_only_ds = OcrEvalDataset(
        cases=[OcrEvalCase(id="only_png", path="sample.png", ground_truth="hi")]
    )
    no_rtr_report = await evaluate_ocr_dataset(
        png_only_ds,
        tmp_path,
        [OcrEvalTarget("fake:v1", FakeOcrModel())],
        warmup=False,
        include_device_rtr=True,
    )
    assert [t.target_name for t in no_rtr_report.targets] == ["fake:v1"]

    # fail_fast=True propagates AIError during warmup and during page evaluation
    with pytest.raises(AIError, match="boom warmup"):
        await evaluate_ocr_dataset(
            png_only_ds,
            tmp_path,
            [OcrEvalTarget("err", _ScriptedOcrModel([AIError("boom warmup")]))],
            warmup=True,
            fail_fast=True,
        )

    with pytest.raises(AIError, match="boom page"):
        await evaluate_ocr_dataset(
            png_only_ds,
            tmp_path,
            [OcrEvalTarget("err", _ScriptedOcrModel([AIError("boom page")]))],
            warmup=False,
            fail_fast=True,
        )
