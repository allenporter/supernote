"""Provider-agnostic OCR evaluation dataset, Rapid Logging metrics, and runner."""

from __future__ import annotations

import asyncio
import io
import logging
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.yaml import DataClassYAMLMixin

from supernote.notebook.converter import ImageConverter, TextConverter
from supernote.notebook.parser import load_notebook
from supernote.server.ai.base import AIError
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt

__all__ = [
    "BUJO_PROMPT_TYPES",
    "CANONICAL_BUJO_MARKERS",
    "LoadedEvalPage",
    "OcrCategorySummary",
    "OcrEvalCase",
    "OcrEvalDataset",
    "OcrEvalSuiteReport",
    "OcrEvalTarget",
    "OcrPageMetrics",
    "OcrTargetCaseResult",
    "OcrTargetReport",
    "ParetoPoint",
    "build_target_report",
    "compute_pareto_frontier",
    "evaluate_ocr_dataset",
    "format_markdown_report",
    "load_eval_case_input",
    "merge_eval_reports",
    "render_pareto_svg",
    "rescore_suite_report",
    "score_ocr_output",
]

PNG_COMPRESS_LEVEL = 1
_LOGGER = logging.getLogger(__name__)
CANONICAL_BUJO_MARKERS: frozenset[str] = frozenset({"•", "X", ">", "<", "o", "-"})
BUJO_PROMPT_TYPES: frozenset[str] = frozenset({"daily", "weekly", "monthly"})

# Matches a canonical Rapid Logging line per `resources/prompts/ocr/common/legend.md`:
# optional 2-space indents, optional `* ` critical signifier, bullet marker, and body.
_BUJO_LINE_RE = re.compile(
    r"^(?P<indent>[ ]*)(?:(?P<star>\*)\s+)?(?P<marker>[•X><o-])\s+(?P<body>.+?)\s*$"
)
# Strips leading bullet/checkbox prefixes and `~~` markers for content-only CER.
_STRIP_PREFIX_RE = re.compile(r"^[ ]*(?:\*\s+)?(?:[•·∙*X×><o\-]|\[[ xX>]\])\s+")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")
_INTERNAL_APOSTROPHE_RE = re.compile(r"(?<=\w)['\u2019](?=\w)")
_WORD_RE = re.compile(r"\w+")


@dataclass
class OcrEvalCase(DataClassYAMLMixin, DataClassJSONMixin):
    """Single page case in an OCR evaluation dataset."""

    id: str
    path: str
    page_index: int = 0
    category: str = "general"
    prompt_type: str | None = None
    language: str | None = None
    ground_truth: str = ""
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("OcrEvalCase.id must be non-empty.")
        if not self.path or not self.path.strip():
            raise ValueError(f"OcrEvalCase({self.id!r}).path must be non-empty.")
        if self.page_index < 0:
            raise ValueError(f"OcrEvalCase({self.id!r}).page_index must be >= 0.")

    @property
    def is_bujo(self) -> bool:
        """Return True when this case evaluates Bullet Journal Rapid Logging."""
        return self.category.startswith("bujo_") or (
            self.prompt_type in BUJO_PROMPT_TYPES
        )


@dataclass
class OcrEvalDataset(DataClassYAMLMixin, DataClassJSONMixin):
    """Declarative collection of OCR evaluation cases loaded from YAML."""

    name: str = "supernote-ocr-eval"
    cases: list[OcrEvalCase] = field(default_factory=list)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"Duplicate OcrEvalCase id: {case.id!r}")
            seen.add(case.id)

    @classmethod
    def load(cls, manifest_path: Path) -> OcrEvalDataset:
        """Load and validate an `OcrEvalDataset` from a YAML manifest file."""
        return cls.from_yaml(manifest_path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class LoadedEvalPage:
    """Rasterized PNG, formatted prompt, and optional embedded RTR text for a case."""

    case: OcrEvalCase
    png_data: bytes
    prompt: str
    device_rtr_text: str | None = None


@dataclass
class OcrPageMetrics(DataClassJSONMixin):
    """Accuracy and Rapid Logging structural scores for one transcribed page."""

    cer: float
    content_cer: float
    wer: float
    word_recall: float
    bujo_expected_items: int
    word_f1: float = 0.0
    bujo_symbol_recall: float | None = None
    bujo_strikethrough_recall: float | None = None
    bujo_indent_accuracy: float | None = None


@dataclass
class OcrTargetCaseResult(DataClassJSONMixin):
    """Result of running a single `OcrEvalTarget` on one `OcrEvalCase`."""

    case_id: str
    category: str
    hypothesis: str
    latency_ms: float
    metrics: OcrPageMetrics
    error: str | None = None


@dataclass
class OcrCategorySummary(DataClassJSONMixin):
    """Aggregated metrics across a slice of evaluation cases."""

    category: str
    page_count: int
    error_count: int
    mean_cer: float
    median_cer: float
    mean_content_cer: float
    mean_wer: float
    mean_word_recall: float
    mean_bujo_symbol_recall: float | None
    mean_bujo_strikethrough_recall: float | None
    mean_bujo_indent_accuracy: float | None
    median_latency_ms: float
    p95_latency_ms: float
    mean_word_f1: float = 0.0


@dataclass
class OcrTargetReport(DataClassJSONMixin):
    """Full evaluation report for a single provider/model target."""

    target_name: str
    model_id: str
    warmup_ms: float
    overall: OcrCategorySummary
    by_category: list[OcrCategorySummary]
    cases: list[OcrTargetCaseResult]


@dataclass
class OcrEvalSuiteReport(DataClassJSONMixin):
    """Multi-provider comparison report across an `OcrEvalDataset`."""

    dataset_name: str
    case_count: int
    targets: list[OcrTargetReport]


@dataclass(frozen=True)
class OcrEvalTarget:
    """Named `OcrModel` instance to benchmark."""

    name: str
    model: OcrModel


@dataclass(frozen=True)
class _ParsedBujoItem:
    indent_spaces: int
    starred: bool
    marker: str
    has_strikethrough: bool
    words: frozenset[str]


def _levenshtein(seq_a: Sequence[str], seq_b: Sequence[str]) -> int:
    if len(seq_a) < len(seq_b):
        return _levenshtein(seq_b, seq_a)
    if not seq_b:
        return len(seq_a)
    prev = list(range(len(seq_b) + 1))
    for i, item_a in enumerate(seq_a):
        curr = [i + 1]
        for j, item_b in enumerate(seq_b):
            ins = prev[j + 1] + 1
            dele = curr[j] + 1
            sub = prev[j] + (0 if item_a == item_b else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_bujo_markup(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _STRIP_PREFIX_RE.sub("", raw_line)
        line = _STRIKETHROUGH_RE.sub(r"\1", line).strip()
        if line:
            cleaned_lines.append(line)
    return " ".join(cleaned_lines)


def _tokenize_words(text: str) -> list[str]:
    return _WORD_RE.findall(_INTERNAL_APOSTROPHE_RE.sub("", text.lower()))


def _parse_bujo_line(line: str) -> _ParsedBujoItem | None:
    match = _BUJO_LINE_RE.match(line)
    if match is None:
        return None
    body = match.group("body")
    has_strike = bool(_STRIKETHROUGH_RE.search(body))
    plain_body = _STRIKETHROUGH_RE.sub(r"\1", body)
    words = frozenset(_tokenize_words(plain_body))
    if not words:
        return None
    return _ParsedBujoItem(
        indent_spaces=len(match.group("indent")),
        starred=match.group("star") is not None,
        marker=match.group("marker"),
        has_strikethrough=has_strike,
        words=words,
    )


def _word_jaccard(words_a: frozenset[str], words_b: frozenset[str]) -> float:
    union = words_a | words_b
    if not union:
        return 0.0
    return len(words_a & words_b) / len(union)


def _score_bujo_structure(
    reference: str, hypothesis: str
) -> tuple[int, float | None, float | None, float | None]:
    ref_items = [
        parsed
        for line in reference.splitlines()
        if (parsed := _parse_bujo_line(line)) is not None
    ]
    if not ref_items:
        return 0, None, None, None

    hyp_lines: list[tuple[str, _ParsedBujoItem | None, frozenset[str]]] = []
    for line in hypothesis.splitlines():
        parsed = _parse_bujo_line(line)
        words = parsed.words if parsed is not None else frozenset(_tokenize_words(line))
        if words:
            hyp_lines.append((line, parsed, words))

    used_hyp_indices: set[int] = set()
    symbol_hits = 0
    strike_total = 0
    strike_hits = 0
    indent_total = 0
    indent_hits = 0

    for ref_item in ref_items:
        if ref_item.has_strikethrough:
            strike_total += 1
        if ref_item.indent_spaces >= 2:
            indent_total += 1

        best_idx: int | None = None
        best_score = 0.0
        for idx, (_, _, hyp_words) in enumerate(hyp_lines):
            if idx in used_hyp_indices:
                continue
            score = _word_jaccard(ref_item.words, hyp_words)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is None or best_score < 0.35:
            continue

        used_hyp_indices.add(best_idx)
        raw_hyp_line, hyp_parsed, _ = hyp_lines[best_idx]

        if (
            hyp_parsed is not None
            and hyp_parsed.marker == ref_item.marker
            and hyp_parsed.starred == ref_item.starred
        ):
            symbol_hits += 1

        if ref_item.has_strikethrough and bool(_STRIKETHROUGH_RE.search(raw_hyp_line)):
            strike_hits += 1

        if ref_item.indent_spaces >= 2:
            leading_spaces = len(raw_hyp_line) - len(raw_hyp_line.lstrip(" "))
            if leading_spaces >= 2:
                indent_hits += 1

    symbol_recall = round(symbol_hits / len(ref_items), 4)
    strike_recall = round(strike_hits / strike_total, 4) if strike_total > 0 else None
    indent_acc = round(indent_hits / indent_total, 4) if indent_total > 0 else None
    return len(ref_items), symbol_recall, strike_recall, indent_acc


def score_ocr_output(
    reference: str,
    hypothesis: str,
    *,
    evaluate_bujo: bool = True,
) -> OcrPageMetrics:
    """Compute character, word, and Bullet Journal Rapid Logging metrics."""
    ref_norm = _normalize_ws(reference)
    hyp_norm = _normalize_ws(hypothesis)

    if not ref_norm:
        empty_match = not hyp_norm
        return OcrPageMetrics(
            cer=0.0 if empty_match else 1.0,
            content_cer=0.0 if empty_match else 1.0,
            wer=0.0 if empty_match else 1.0,
            word_recall=1.0 if empty_match else 0.0,
            word_f1=1.0 if empty_match else 0.0,
            bujo_expected_items=0,
        )

    cer = _levenshtein(ref_norm, hyp_norm) / len(ref_norm)

    ref_content = _normalize_ws(_strip_bujo_markup(reference)).lower()
    hyp_content = _normalize_ws(_strip_bujo_markup(hypothesis)).lower()
    content_cer = (
        _levenshtein(ref_content, hyp_content) / len(ref_content)
        if ref_content
        else cer
    )

    ref_words = ref_norm.split(" ")
    hyp_words = hyp_norm.split(" ") if hyp_norm else []
    wer = _levenshtein(ref_words, hyp_words) / len(ref_words)

    ref_tokens = _tokenize_words(ref_content or reference)
    hyp_tokens = _tokenize_words(hyp_content or hypothesis)
    if not ref_tokens:
        word_recall = 1.0
        word_f1 = 1.0 if not hyp_tokens else 0.0
    else:
        matched_tokens = sum((Counter(ref_tokens) & Counter(hyp_tokens)).values())
        word_recall = matched_tokens / len(ref_tokens)
        word_f1 = (
            2 * matched_tokens / (len(ref_tokens) + len(hyp_tokens))
            if hyp_tokens
            else 0.0
        )

    bujo_count, bujo_sym, bujo_strike, bujo_indent = (
        _score_bujo_structure(reference, hypothesis)
        if evaluate_bujo
        else (0, None, None, None)
    )

    return OcrPageMetrics(
        cer=round(cer, 4),
        content_cer=round(content_cer, 4),
        wer=round(wer, 4),
        word_recall=round(word_recall, 4),
        word_f1=round(word_f1, 4),
        bujo_expected_items=bujo_count,
        bujo_symbol_recall=bujo_sym,
        bujo_strikethrough_recall=bujo_strike,
        bujo_indent_accuracy=bujo_indent,
    )


def load_eval_case_input(case: OcrEvalCase, base_dir: Path) -> LoadedEvalPage:
    """Load and rasterize a `.note` page or `.png` file and format its OCR prompt."""
    asset_path = (base_dir / case.path).resolve()
    if not asset_path.exists():
        raise FileNotFoundError(
            f"Eval asset for case {case.id!r} not found: {asset_path}"
        )

    suffix = asset_path.suffix.lower()
    device_rtr_text: str | None = None
    if suffix == ".note":
        notebook = load_notebook(str(asset_path), policy="loose")
        total_pages = notebook.total_pages
        if case.page_index >= total_pages:
            raise IndexError(
                f"Case {case.id!r} page_index={case.page_index} out of range "
                f"for {asset_path.name} ({total_pages} page(s))."
            )
        page = notebook.page(case.page_index)
        page_id = page.page_id or f"page_{case.page_index}"
        img = ImageConverter(notebook).convert(case.page_index)  # type: ignore[no-untyped-call]
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
        png_data = buf.getvalue()

        raw_rtr = TextConverter(notebook).convert(case.page_index)  # type: ignore[no-untyped-call]
        device_rtr_text = raw_rtr.strip() if raw_rtr else None
    elif suffix == ".png":
        png_data = asset_path.read_bytes()
        page_id = f"{asset_path.stem}_p{case.page_index}"
    else:
        raise ValueError(
            f"Unsupported asset extension {suffix!r} for case {case.id!r}; "
            "expected '.note' or '.png'."
        )

    metadata = PageMetadata(
        file_name=asset_path.name,
        page_index=case.page_index,
        page_id=page_id,
        notebook_create_time=None,
    )
    prompt = format_ocr_prompt(metadata, custom_type=case.prompt_type)
    return LoadedEvalPage(
        case=case,
        png_data=png_data,
        prompt=prompt,
        device_rtr_text=device_rtr_text,
    )


def _mean_optional(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(statistics.mean(present), 4)


def _summarize_results(
    category: str, results: Sequence[OcrTargetCaseResult]
) -> OcrCategorySummary:
    if not results:
        raise ValueError("Cannot summarize an empty result sequence.")
    cers = [r.metrics.cer for r in results]
    content_cers = [r.metrics.content_cer for r in results]
    wers = [r.metrics.wer for r in results]
    recalls = [r.metrics.word_recall for r in results]
    f1s = [r.metrics.word_f1 for r in results]
    latencies = sorted(r.latency_ms for r in results)
    p95_idx = max(0, math.ceil(0.95 * len(latencies)) - 1)

    return OcrCategorySummary(
        category=category,
        page_count=len(results),
        error_count=sum(1 for r in results if r.error is not None),
        mean_cer=round(statistics.mean(cers), 4),
        median_cer=round(statistics.median(cers), 4),
        mean_content_cer=round(statistics.mean(content_cers), 4),
        mean_wer=round(statistics.mean(wers), 4),
        mean_word_recall=round(statistics.mean(recalls), 4),
        mean_word_f1=round(statistics.mean(f1s), 4),
        mean_bujo_symbol_recall=_mean_optional(
            [r.metrics.bujo_symbol_recall for r in results]
        ),
        mean_bujo_strikethrough_recall=_mean_optional(
            [r.metrics.bujo_strikethrough_recall for r in results]
        ),
        mean_bujo_indent_accuracy=_mean_optional(
            [r.metrics.bujo_indent_accuracy for r in results]
        ),
        median_latency_ms=round(statistics.median(latencies), 1),
        p95_latency_ms=round(latencies[p95_idx], 1),
    )


def build_target_report(
    target_name: str,
    model_id: str,
    warmup_ms: float,
    case_results: list[OcrTargetCaseResult],
) -> OcrTargetReport:
    """Aggregate per-page `OcrTargetCaseResult` items into an `OcrTargetReport`."""
    categories_seen: list[str] = []
    for res in case_results:
        if res.category not in categories_seen:
            categories_seen.append(res.category)

    by_category = [
        _summarize_results(cat, [r for r in case_results if r.category == cat])
        for cat in categories_seen
    ]
    return OcrTargetReport(
        target_name=target_name,
        model_id=model_id,
        warmup_ms=round(warmup_ms, 1),
        overall=_summarize_results("all", case_results),
        by_category=by_category,
        cases=case_results,
    )


def _error_page_metrics() -> OcrPageMetrics:
    return OcrPageMetrics(
        cer=1.0,
        content_cer=1.0,
        wer=1.0,
        word_recall=0.0,
        word_f1=0.0,
        bujo_expected_items=0,
    )


async def evaluate_ocr_dataset(
    dataset: OcrEvalDataset,
    base_dir: Path,
    targets: Sequence[OcrEvalTarget],
    *,
    warmup: bool = True,
    include_device_rtr: bool = False,
    fail_fast: bool = False,
    page_timeout_s: float | None = 90.0,
) -> OcrEvalSuiteReport:
    """Run all `targets` against `dataset` and return an `OcrEvalSuiteReport`."""
    if not dataset.cases:
        raise ValueError("OcrEvalDataset must contain at least one case.")
    if not targets and not include_device_rtr:
        raise ValueError(
            "At least one OcrEvalTarget (or include_device_rtr) is required."
        )

    loaded_pages = [load_eval_case_input(case, base_dir) for case in dataset.cases]
    target_reports: list[OcrTargetReport] = []
    total_pages = len(loaded_pages)

    for target in targets:
        warmup_ms = 0.0
        if warmup:
            warmup_page = loaded_pages[0]
            _LOGGER.info("[%s] warming up on %s...", target.name, warmup_page.case.id)
            t0 = time.perf_counter()
            try:
                coro = target.model.extract_text(
                    warmup_page.png_data, warmup_page.prompt
                )
                if page_timeout_s is not None:
                    await asyncio.wait_for(coro, timeout=page_timeout_s)
                else:
                    await coro
            except (AIError, TimeoutError):
                if fail_fast:
                    raise
            warmup_ms = (time.perf_counter() - t0) * 1000.0

        case_results: list[OcrTargetCaseResult] = []
        for idx, page in enumerate(loaded_pages, start=1):
            t_start = time.perf_counter()
            error_msg: str | None = None
            try:
                coro = target.model.extract_text(page.png_data, page.prompt)
                if page_timeout_s is not None:
                    hypothesis = await asyncio.wait_for(coro, timeout=page_timeout_s)
                else:
                    hypothesis = await coro
            except TimeoutError:
                if fail_fast:
                    raise
                hypothesis = ""
                error_msg = f"Timed out after {page_timeout_s:.1f}s"
            except AIError as err:
                if fail_fast:
                    raise
                hypothesis = ""
                error_msg = str(err)
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0

            metrics = (
                score_ocr_output(
                    page.case.ground_truth,
                    hypothesis,
                    evaluate_bujo=page.case.is_bujo,
                )
                if error_msg is None
                else _error_page_metrics()
            )
            _LOGGER.info(
                "[%s] %d/%d %s -> CER=%.1f%% F1=%.1f%% (%.1f ms)%s",
                target.name,
                idx,
                total_pages,
                page.case.id,
                metrics.cer * 100.0,
                metrics.word_f1 * 100.0,
                elapsed_ms,
                f" ERROR={error_msg}" if error_msg else "",
            )
            case_results.append(
                OcrTargetCaseResult(
                    case_id=page.case.id,
                    category=page.case.category,
                    hypothesis=hypothesis,
                    latency_ms=round(elapsed_ms, 1),
                    metrics=metrics,
                    error=error_msg,
                )
            )

        target_reports.append(
            build_target_report(
                target_name=target.name,
                model_id=target.model.model_id,
                warmup_ms=warmup_ms,
                case_results=case_results,
            )
        )

    if include_device_rtr:
        rtr_pages = [p for p in loaded_pages if p.device_rtr_text is not None]
        if rtr_pages:
            rtr_results = [
                OcrTargetCaseResult(
                    case_id=p.case.id,
                    category=p.case.category,
                    hypothesis=p.device_rtr_text or "",
                    latency_ms=0.0,
                    metrics=score_ocr_output(
                        p.case.ground_truth,
                        p.device_rtr_text or "",
                        evaluate_bujo=p.case.is_bujo,
                    ),
                )
                for p in rtr_pages
            ]
            target_reports.append(
                build_target_report(
                    target_name="device-rtr",
                    model_id="supernote-rtr-embedded",
                    warmup_ms=0.0,
                    case_results=rtr_results,
                )
            )

    return OcrEvalSuiteReport(
        dataset_name=dataset.name,
        case_count=len(loaded_pages),
        targets=target_reports,
    )


def rescore_suite_report(
    report: OcrEvalSuiteReport,
    dataset: OcrEvalDataset,
) -> OcrEvalSuiteReport:
    """Recompute per-case metrics, categories, and summaries against `dataset`."""
    cases_by_id = {case.id: case for case in dataset.cases}
    rescored_targets: list[OcrTargetReport] = []
    for target in report.targets:
        rescored_cases: list[OcrTargetCaseResult] = []
        for item in target.cases:
            if item.case_id not in cases_by_id:
                raise KeyError(
                    f"Case {item.case_id!r} in target {target.target_name!r} "
                    f"not found in dataset {dataset.name!r}."
                )
            case = cases_by_id[item.case_id]
            metrics = (
                score_ocr_output(
                    case.ground_truth,
                    item.hypothesis,
                    evaluate_bujo=case.is_bujo,
                )
                if item.error is None
                else _error_page_metrics()
            )
            rescored_cases.append(
                OcrTargetCaseResult(
                    case_id=item.case_id,
                    category=case.category,
                    hypothesis=item.hypothesis,
                    latency_ms=item.latency_ms,
                    metrics=metrics,
                    error=item.error,
                )
            )
        rescored_targets.append(
            build_target_report(
                target_name=target.target_name,
                model_id=target.model_id,
                warmup_ms=target.warmup_ms,
                case_results=rescored_cases,
            )
        )
    return OcrEvalSuiteReport(
        dataset_name=dataset.name,
        case_count=report.case_count,
        targets=rescored_targets,
    )


def merge_eval_reports(reports: Sequence[OcrEvalSuiteReport]) -> OcrEvalSuiteReport:
    """Merge multiple `OcrEvalSuiteReport` runs for the same dataset by `target_name`.

    Later reports replace earlier targets with the same `target_name` in-place while
    preserving first-seen target order, enabling incremental provider benchmarking
    across different machines and environments.
    """
    if not reports:
        raise ValueError("merge_eval_reports requires at least one report.")

    dataset_name = reports[0].dataset_name
    merged_targets: dict[str, OcrTargetReport] = {}
    max_case_count = 0
    for report in reports:
        if report.dataset_name != dataset_name:
            raise ValueError(
                f"Cannot merge reports from different datasets: "
                f"{dataset_name!r} vs {report.dataset_name!r}."
            )
        max_case_count = max(max_case_count, report.case_count)
        for target in report.targets:
            merged_targets[target.target_name] = target

    return OcrEvalSuiteReport(
        dataset_name=dataset_name,
        case_count=max_case_count,
        targets=list(merged_targets.values()),
    )


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def format_markdown_report(report: OcrEvalSuiteReport) -> str:
    """Format an `OcrEvalSuiteReport` as a GitHub-flavored Markdown comparison table."""
    lines: list[str] = [
        f"# OCR Evaluation Report: `{report.dataset_name}` ({report.case_count} pages)",
        "",
        "## Overall Summary",
        "",
        "| Target | Model | Pages | Mean CER | Median CER | Content CER | Word F1 | Word Recall | BuJo Symbol Recall | Median Latency | P95 Latency | Errors |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for target in report.targets:
        ov = target.overall
        lines.append(
            f"| `{target.target_name}` | `{target.model_id}` | {ov.page_count} | "
            f"{_fmt_pct(ov.mean_cer)} | {_fmt_pct(ov.median_cer)} | "
            f"{_fmt_pct(ov.mean_content_cer)} | {_fmt_pct(ov.mean_word_f1)} | "
            f"{_fmt_pct(ov.mean_word_recall)} | {_fmt_pct(ov.mean_bujo_symbol_recall)} | "
            f"{ov.median_latency_ms:.1f} ms | {ov.p95_latency_ms:.1f} ms | {ov.error_count} |"
        )

    lines.extend(
        [
            "",
            "## Breakdown by Category",
            "",
            "| Target | Category | Pages | Mean CER | Content CER | Word F1 | Word Recall | BuJo Symbol Recall | BuJo Indent | BuJo Strike | Median Latency |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for target in report.targets:
        for cat in target.by_category:
            lines.append(
                f"| `{target.target_name}` | `{cat.category}` | {cat.page_count} | "
                f"{_fmt_pct(cat.mean_cer)} | {_fmt_pct(cat.mean_content_cer)} | "
                f"{_fmt_pct(cat.mean_word_f1)} | {_fmt_pct(cat.mean_word_recall)} | "
                f"{_fmt_pct(cat.mean_bujo_symbol_recall)} | "
                f"{_fmt_pct(cat.mean_bujo_indent_accuracy)} | "
                f"{_fmt_pct(cat.mean_bujo_strikethrough_recall)} | "
                f"{cat.median_latency_ms:.1f} ms |"
            )

    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ParetoPoint:
    """Latency-vs-quality coordinate for a single evaluated `OcrTargetReport`."""

    target_name: str
    model_id: str
    latency_ms: float
    score: float
    is_pareto: bool


def compute_pareto_frontier(
    report: OcrEvalSuiteReport,
    *,
    score_fn: Callable[[OcrTargetReport], float | None] | None = None,
    use_p95_latency: bool = False,
) -> list[ParetoPoint]:
    """Compute latency-minimizing, score-maximizing Pareto status across targets.

    Targets without live latency measurements (`latency_ms <= 0`, such as pre-embedded
    `device-rtr`) or where `score_fn` returns `None` are excluded. Returned points are
    sorted by `(latency_ms, -score)`.
    """
    extractor = score_fn or (lambda t: t.overall.mean_word_f1)
    candidates: list[tuple[float, float, OcrTargetReport]] = []
    for target in report.targets:
        lat = (
            target.overall.p95_latency_ms
            if use_p95_latency
            else target.overall.median_latency_ms
        )
        if lat <= 0.0:
            continue
        val = extractor(target)
        if val is None:
            continue
        candidates.append((lat, val, target))

    candidates.sort(key=lambda item: (item[0], -item[1]))
    points: list[ParetoPoint] = []
    best_score = -math.inf
    for lat, val, target in candidates:
        is_pareto = val > best_score
        if is_pareto:
            best_score = val
        points.append(
            ParetoPoint(
                target_name=target.target_name,
                model_id=target.model_id,
                latency_ms=lat,
                score=val,
                is_pareto=is_pareto,
            )
        )
    return points


_KNOWN_PARETO_LABELS: dict[str, str] = {
    "apple:vision-accurate": "Apple Vision Accurate",
    "apple:vision-fast": "Apple Vision Fast",
    "supernote-on-device": "Supernote On-Device",
    "gemini:gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
    "gemini:gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini:gemini-3.8-flash": "Gemini 3.8 Flash",
}


def _format_pareto_label(target_name: str) -> str:
    """Format a CLI target identifier into a clear chart label."""
    if target_name in _KNOWN_PARETO_LABELS:
        return _KNOWN_PARETO_LABELS[target_name]
    if target_name.startswith("gemini:"):
        raw = target_name.removeprefix("gemini:")
        if raw.startswith("gemini-"):
            parts = raw.removeprefix("gemini-").split("-")
            titled = (
                "-".join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else ""
            )
            return f"Gemini {parts[0]} {titled}".strip()
    if target_name.startswith("apple:vision-"):
        mode = target_name.removeprefix("apple:vision-").capitalize()
        return f"Apple Vision {mode}"
    return target_name


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    pad: float = 3.0,
) -> bool:
    return not (
        a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1]
    )


def _segment_hits_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    box: tuple[float, float, float, float],
) -> bool:
    """Return True if interior of segment (x1,y1)-(x2,y2) passes through `box`."""
    bx0, by0, bx1, by1 = box
    for t in (0.12, 0.25, 0.38, 0.5, 0.62, 0.75, 0.88):
        sx_t = x1 + (x2 - x1) * t
        sy_t = y1 + (y2 - y1) * t
        if bx0 <= sx_t <= bx1 and by0 <= sy_t <= by1:
            return True
    return False


def _render_pareto_panel_svg(
    points: Sequence[ParetoPoint],
    *,
    x0: float,
    y0: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
) -> list[str]:
    pad_l, pad_r, pad_t, pad_b = 52.0, 16.0, 34.0, 40.0
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    plot_left = x0 + pad_l
    plot_right = plot_left + plot_w
    plot_top = y0 + pad_t
    plot_bottom = plot_top + plot_h
    inner_y_pad = 26.0
    usable_h = plot_h - 2.0 * inner_y_pad
    min_log, max_log = 1.74, 4.32  # ~55 ms to ~21,000 ms

    def sx(ms: float) -> float:
        clamped = min(max(math.log10(ms), min_log), max_log)
        return plot_left + (clamped - min_log) / (max_log - min_log) * plot_w

    def sy(score: float) -> float:
        clamped = min(max(score, 0.0), 1.0)
        return plot_top + inner_y_pad + (1.0 - clamped) * usable_h

    out: list[str] = [
        f'<text x="{plot_left:.1f}" y="{y0 + 20:.1f}" class="panel-title">{xml_escape(title)}</text>',
        f'<rect x="{plot_left:.1f}" y="{plot_top:.1f}" width="{plot_w:.1f}" height="{plot_h:.1f}" class="plot-bg" rx="6" />',
    ]

    for pct in (0.0, 0.25, 0.5, 0.75, 1.0):
        gy = sy(pct)
        out.append(
            f'<line x1="{plot_left:.1f}" y1="{gy:.1f}" x2="{plot_right:.1f}" y2="{gy:.1f}" class="grid" />'
        )
        out.append(
            f'<text x="{plot_left - 8:.1f}" y="{gy + 4:.1f}" text-anchor="end" class="tick">{int(pct * 100)}%</text>'
        )

    for tick_ms, label in (
        (100.0, "100 ms"),
        (300.0, "300 ms"),
        (1000.0, "1 s"),
        (3000.0, "3 s"),
        (10000.0, "10 s"),
    ):
        gx = sx(tick_ms)
        out.append(
            f'<line x1="{gx:.1f}" y1="{plot_top:.1f}" x2="{gx:.1f}" y2="{plot_bottom:.1f}" class="grid" />'
        )
        out.append(
            f'<text x="{gx:.1f}" y="{plot_bottom + 18:.1f}" text-anchor="middle" class="tick">{label}</text>'
        )

    out.append(
        f'<text x="{plot_left + plot_w / 2:.1f}" y="{y0 + height - 4:.1f}" text-anchor="middle" class="axis-label">Median Page Latency (log scale, lower is faster)</text>'
    )
    mid_y = plot_top + plot_h / 2
    out.append(
        f'<text x="{x0 + 14:.1f}" y="{mid_y:.1f}" text-anchor="middle" transform="rotate(-90 {x0 + 14:.1f} {mid_y:.1f})" class="axis-label">{xml_escape(y_label)}</text>'
    )

    frontier = [p for p in points if p.is_pareto]
    frontier_segments: list[tuple[float, float, float, float]] = []
    if len(frontier) >= 2:
        step_coords: list[str] = [
            f"{sx(frontier[0].latency_ms):.1f},{sy(frontier[0].score):.1f}"
        ]
        for prev_pt, next_pt in zip(frontier, frontier[1:], strict=False):
            x1, y1 = sx(prev_pt.latency_ms), sy(prev_pt.score)
            x2, y2 = sx(next_pt.latency_ms), sy(next_pt.score)
            frontier_segments.append((x1, y1, x2, y2))
            step_coords.append(f"{x2:.1f},{y1:.1f}")
            step_coords.append(f"{x2:.1f},{y2:.1f}")
        out.append(
            f'<polyline points="{" ".join(step_coords)}" class="frontier-step" />'
        )
        direct_coords = " ".join(
            f"{sx(p.latency_ms):.1f},{sy(p.score):.1f}" for p in frontier
        )
        out.append(f'<polyline points="{direct_coords}" class="frontier-line" />')

    coords = [(sx(pt.latency_ms), sy(pt.score)) for pt in points]
    point_boxes = [(px - 6.0, py - 6.0, px + 6.0, py + 6.0) for px, py in coords]
    placed_boxes: list[tuple[float, float, float, float]] = []

    candidate_offsets: list[tuple[float, float, str]] = [
        (10.0, 4.0, "start"),
        (-10.0, 4.0, "end"),
        (9.0, -11.0, "start"),
        (-9.0, -11.0, "end"),
        (9.0, 19.0, "start"),
        (-9.0, 19.0, "end"),
        (-4.0, -12.0, "start"),
        (4.0, -12.0, "end"),
        (-4.0, 20.0, "start"),
        (4.0, 20.0, "end"),
        (10.0, -24.0, "start"),
        (-10.0, -24.0, "end"),
        (10.0, 31.0, "start"),
        (-10.0, 31.0, "end"),
        (-28.0, -16.0, "start"),
        (28.0, -16.0, "end"),
        (-28.0, 24.0, "start"),
        (28.0, 24.0, "end"),
        (10.0, -36.0, "start"),
        (-10.0, -36.0, "end"),
        (10.0, 43.0, "start"),
        (-10.0, 43.0, "end"),
    ]

    leader_lines: list[str] = []
    point_circles: list[str] = []
    label_texts: list[str] = []

    order = sorted(
        range(len(points)),
        key=lambda i: (-coords[i][0], coords[i][1]),
    )
    placements: dict[
        int, tuple[float, float, str, str, tuple[float, float, float, float]]
    ] = {}

    for idx in order:
        pt = points[idx]
        px, py = coords[idx]
        label_text = f"{_format_pareto_label(pt.target_name)} ({pt.score * 100:.1f}%)"
        char_w = 6.3 if pt.is_pareto else 5.8
        est_w = len(label_text) * char_w + 3.0
        est_h = 13.0

        best_choice: (
            tuple[float, float, float, str, tuple[float, float, float, float]] | None
        ) = None
        prefer_end = px > plot_left + plot_w * 0.48

        for dx, dy, anchor in candidate_offsets:
            tx = px + dx
            ty = py + dy
            if anchor == "start":
                box = (tx, ty - est_h + 2.0, tx + est_w, ty + 3.0)
            else:
                box = (tx - est_w, ty - est_h + 2.0, tx, ty + 3.0)

            penalty = math.hypot(dx, dy)
            if (anchor == "end") != prefer_end:
                penalty += 6.0
            if (
                box[0] < plot_left + 4.0
                or box[2] > plot_right - 4.0
                or box[1] < plot_top + 3.0
                or box[3] > plot_bottom - 3.0
            ):
                penalty += 30000.0
            for pbox in point_boxes:
                if _boxes_overlap(box, pbox, pad=2.0):
                    penalty += 25000.0
            for lbox in placed_boxes:
                if _boxes_overlap(box, lbox, pad=3.5):
                    penalty += 15000.0
            for sx1, sy1, sx2, sy2 in frontier_segments:
                if _segment_hits_box(sx1, sy1, sx2, sy2, box):
                    penalty += 500.0

            if best_choice is None or penalty < best_choice[0]:
                best_choice = (penalty, tx, ty, anchor, box)

        assert best_choice is not None
        _, tx, ty, anchor, chosen_box = best_choice
        placed_boxes.append(chosen_box)
        placements[idx] = (tx, ty, anchor, label_text, chosen_box)

    for idx, pt in enumerate(points):
        px, py = coords[idx]
        cls = "pt-pareto" if pt.is_pareto else "pt-dom"
        r = 6.0 if pt.is_pareto else 5.0
        point_circles.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r:.1f}" class="{cls}" />'
        )
        tx, ty, anchor, label_text, box = placements[idx]
        lbl_cls = "lbl-pareto" if pt.is_pareto else "lbl-dom"
        lx = min(max(px, box[0]), box[2])
        ly = min(max(py, box[1]), box[3])
        if math.hypot(lx - px, ly - py) > 12.0:
            leader_lines.append(
                f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" class="leader" />'
            )
        label_texts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" class="{lbl_cls}">'
            f"{xml_escape(label_text)}</text>"
        )

    out.extend(leader_lines)
    out.extend(point_circles)
    out.extend(label_texts)
    return out


def render_pareto_svg(report: OcrEvalSuiteReport) -> str:
    """Render a two-panel SVG Pareto frontier chart (Word F1 & Handwritten BuJo vs Latency)."""

    def _handwritten_bujo_recall(target: OcrTargetReport) -> float | None:
        vals = [
            c.mean_bujo_symbol_recall
            for c in target.by_category
            if c.category in {"bujo_daily", "bujo_monthly"}
            and c.mean_bujo_symbol_recall is not None
        ]
        return statistics.mean(vals) if vals else target.overall.mean_bujo_symbol_recall

    f1_points = compute_pareto_frontier(report)
    bujo_points = compute_pareto_frontier(report, score_fn=_handwritten_bujo_recall)

    svg_lines: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 400" width="960" height="400" role="img" aria-label="OCR Accuracy vs Latency Pareto Frontier">',
        "  <style>",
        "    .card { fill: #ffffff; stroke: #e2e8f0; stroke-width: 1.5; }",
        "    .plot-bg { fill: #f8fafc; stroke: #e2e8f0; stroke-width: 1; }",
        "    .grid { stroke: #e2e8f0; stroke-width: 1; stroke-dasharray: 3 3; }",
        "    .title { font: 600 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #0f172a; }",
        "    .subtitle { font: 400 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #64748b; }",
        "    .panel-title { font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #1e293b; }",
        "    .axis-label { font: 500 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #475569; }",
        "    .tick { font: 400 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #64748b; }",
        "    .frontier-step { fill: none; stroke: #93c5fd; stroke-width: 1.5; stroke-dasharray: 4 3; }",
        "    .frontier-line { fill: none; stroke: #2563eb; stroke-width: 2.5; }",
        "    .leader { stroke: #cbd5e1; stroke-width: 1; }",
        "    .pt-pareto { fill: #2563eb; stroke: #ffffff; stroke-width: 2; }",
        "    .pt-dom { fill: #94a3b8; stroke: #ffffff; stroke-width: 1.5; }",
        "    .lbl-pareto { font: 600 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #0f172a; }",
        "    .lbl-dom { font: 400 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #64748b; }",
        "    @media (prefers-color-scheme: dark) {",
        "      .card { fill: #0f172a; stroke: #334155; }",
        "      .plot-bg { fill: #1e293b; stroke: #334155; }",
        "      .grid { stroke: #334155; }",
        "      .title, .panel-title, .lbl-pareto { fill: #f8fafc; }",
        "      .subtitle, .axis-label, .tick, .lbl-dom { fill: #94a3b8; }",
        "      .frontier-step { stroke: #1d4ed8; }",
        "      .frontier-line { stroke: #60a5fa; }",
        "      .leader { stroke: #475569; }",
        "      .pt-pareto { fill: #60a5fa; stroke: #0f172a; }",
        "      .pt-dom { fill: #64748b; stroke: #0f172a; }",
        "    }",
        "  </style>",
        '  <rect x="1" y="1" width="958" height="398" rx="12" class="card" />',
        f'  <text x="24" y="30" class="title">OCR Quality vs. Latency Pareto Frontier ({xml_escape(report.dataset_name)}, {report.case_count} pages)</text>',
        '  <text x="24" y="48" class="subtitle">Solid blue = Pareto-optimal (non-dominated); gray = dominated.</text>',
    ]
    svg_lines.extend(
        _render_pareto_panel_svg(
            f1_points,
            x0=12.0,
            y0=60.0,
            width=464.0,
            height=328.0,
            title="1. Transcript Capture (Word F1)",
            y_label="Mean Word F1",
        )
    )
    svg_lines.extend(
        _render_pareto_panel_svg(
            bujo_points,
            x0=484.0,
            y0=60.0,
            width=464.0,
            height=328.0,
            title="2. Handwritten Rapid Logging (BuJo Symbol Recall)",
            y_label="BuJo Symbol Recall",
        )
    )
    svg_lines.append("</svg>\n")
    return "\n".join(svg_lines)
