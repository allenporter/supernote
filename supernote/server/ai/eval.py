"""Provider-agnostic OCR evaluation dataset, Rapid Logging metrics, and runner."""

from __future__ import annotations

import io
import math
import re
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.yaml import DataClassYAMLMixin

from supernote.notebook.converter import ImageConverter, TextConverter
from supernote.notebook.parser import load_notebook
from supernote.server.ai.base import AIError
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt

__all__ = [
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
    "evaluate_ocr_dataset",
    "format_markdown_report",
    "load_eval_case_input",
    "merge_eval_reports",
    "score_ocr_output",
]

PNG_COMPRESS_LEVEL = 1
CANONICAL_BUJO_MARKERS: frozenset[str] = frozenset({"•", "X", ">", "<", "o", "-"})

# Matches a canonical Rapid Logging line per `resources/prompts/ocr/common/legend.md`:
# optional 2-space indents, optional `* ` critical signifier, bullet marker, and body.
_BUJO_LINE_RE = re.compile(
    r"^(?P<indent>[ ]*)(?:(?P<star>\*)\s+)?(?P<marker>[•X><o-])\s+(?P<body>.+?)\s*$"
)
# Strips leading bullet/checkbox prefixes and `~~` markers for content-only CER.
_STRIP_PREFIX_RE = re.compile(r"^[ ]*(?:\*\s+)?(?:[•·∙*X×><o\-]|\[[ xX>]\])\s+")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")
_WORD_RE = re.compile(r"\w+")


@dataclass
class OcrEvalCase(DataClassYAMLMixin, DataClassJSONMixin):
    """Single page case in an OCR evaluation dataset."""

    id: str
    path: str
    page_index: int = 0
    category: str = "general"
    prompt_type: str | None = None
    ground_truth: str = ""
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("OcrEvalCase.id must be non-empty.")
        if not self.path or not self.path.strip():
            raise ValueError(f"OcrEvalCase({self.id!r}).path must be non-empty.")
        if self.page_index < 0:
            raise ValueError(f"OcrEvalCase({self.id!r}).page_index must be >= 0.")


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
    return _WORD_RE.findall(text.lower())


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


def score_ocr_output(reference: str, hypothesis: str) -> OcrPageMetrics:
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
            bujo_expected_items=0,
        )

    cer = _levenshtein(ref_norm, hyp_norm) / len(ref_norm)

    ref_content = _normalize_ws(_strip_bujo_markup(reference))
    hyp_content = _normalize_ws(_strip_bujo_markup(hypothesis))
    content_cer = (
        _levenshtein(ref_content, hyp_content) / len(ref_content)
        if ref_content
        else cer
    )

    ref_words = ref_norm.split(" ")
    hyp_words = hyp_norm.split(" ") if hyp_norm else []
    wer = _levenshtein(ref_words, hyp_words) / len(ref_words)

    ref_tokens = _tokenize_words(ref_content or reference)
    hyp_token_set = frozenset(_tokenize_words(hyp_content or hypothesis))
    matched_tokens = sum(1 for tok in ref_tokens if tok in hyp_token_set)
    word_recall = matched_tokens / len(ref_tokens) if ref_tokens else 1.0

    bujo_count, bujo_sym, bujo_strike, bujo_indent = _score_bujo_structure(
        reference, hypothesis
    )

    return OcrPageMetrics(
        cer=round(cer, 4),
        content_cer=round(content_cer, 4),
        wer=round(wer, 4),
        word_recall=round(word_recall, 4),
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


def _build_target_report(
    target_name: str,
    model_id: str,
    warmup_ms: float,
    case_results: list[OcrTargetCaseResult],
) -> OcrTargetReport:
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


async def evaluate_ocr_dataset(
    dataset: OcrEvalDataset,
    base_dir: Path,
    targets: Sequence[OcrEvalTarget],
    *,
    warmup: bool = True,
    include_device_rtr: bool = False,
    fail_fast: bool = False,
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

    for target in targets:
        warmup_ms = 0.0
        if warmup:
            warmup_page = loaded_pages[0]
            t0 = time.perf_counter()
            try:
                await target.model.extract_text(
                    warmup_page.png_data, warmup_page.prompt
                )
            except AIError:
                if fail_fast:
                    raise
            warmup_ms = (time.perf_counter() - t0) * 1000.0

        case_results: list[OcrTargetCaseResult] = []
        for page in loaded_pages:
            t_start = time.perf_counter()
            error_msg: str | None = None
            try:
                hypothesis = await target.model.extract_text(page.png_data, page.prompt)
            except AIError as err:
                if fail_fast:
                    raise
                hypothesis = ""
                error_msg = str(err)
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0

            metrics = (
                score_ocr_output(page.case.ground_truth, hypothesis)
                if error_msg is None
                else OcrPageMetrics(
                    cer=1.0,
                    content_cer=1.0,
                    wer=1.0,
                    word_recall=0.0,
                    bujo_expected_items=0,
                )
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
            _build_target_report(
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
                        p.case.ground_truth, p.device_rtr_text or ""
                    ),
                )
                for p in rtr_pages
            ]
            target_reports.append(
                _build_target_report(
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
        "| Target | Model | Pages | Mean CER | Median CER | Content CER | Word Recall | BuJo Symbol Recall | Median Latency | P95 Latency | Errors |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for target in report.targets:
        ov = target.overall
        lines.append(
            f"| `{target.target_name}` | `{target.model_id}` | {ov.page_count} | "
            f"{_fmt_pct(ov.mean_cer)} | {_fmt_pct(ov.median_cer)} | "
            f"{_fmt_pct(ov.mean_content_cer)} | {_fmt_pct(ov.mean_word_recall)} | "
            f"{_fmt_pct(ov.mean_bujo_symbol_recall)} | "
            f"{ov.median_latency_ms:.1f} ms | {ov.p95_latency_ms:.1f} ms | {ov.error_count} |"
        )

    lines.extend(
        [
            "",
            "## Breakdown by Category",
            "",
            "| Target | Category | Pages | Mean CER | Content CER | Word Recall | BuJo Symbol Recall | BuJo Indent | BuJo Strike | Median Latency |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for target in report.targets:
        for cat in target.by_category:
            lines.append(
                f"| `{target.target_name}` | `{cat.category}` | {cat.page_count} | "
                f"{_fmt_pct(cat.mean_cer)} | {_fmt_pct(cat.mean_content_cer)} | "
                f"{_fmt_pct(cat.mean_word_recall)} | {_fmt_pct(cat.mean_bujo_symbol_recall)} | "
                f"{_fmt_pct(cat.mean_bujo_indent_accuracy)} | "
                f"{_fmt_pct(cat.mean_bujo_strikethrough_recall)} | "
                f"{cat.median_latency_ms:.1f} ms |"
            )

    return "\n".join(lines) + "\n"
