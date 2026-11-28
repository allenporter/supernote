"""Repeatable large-notebook summarization evaluation harness and quality scorer."""

from __future__ import annotations

import json
import re
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

import supernote.server.db.models  # noqa: F401
from supernote.models.summary import METADATA_SEGMENTS
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import SummaryResponse, SummarySegment
from supernote.server.components.summary.config import SummaryConfig
from supernote.server.components.summary.processor import SummaryModule
from supernote.server.components.summary.service import SummaryService
from supernote.server.config import AuthConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import LocalBlobStorage
from supernote.server.services.coordination import SqliteCoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_summary_id

__all__ = [
    "DeterministicFakeSummaryModel",
    "SummaryCallTrace",
    "SummaryEvalAppendUpdate",
    "SummaryEvalDataset",
    "SummaryEvalFact",
    "SummaryEvalIncrementalUpdates",
    "SummaryEvalMidEditUpdate",
    "SummaryEvalNotebook",
    "SummaryEvalPage",
    "SummaryEvalReport",
    "SummaryFactResult",
    "SummaryIncrementalResult",
    "SummaryNotebookMetrics",
    "format_markdown_report",
    "load_summary_eval_dataset",
    "run_summary_eval",
]

_PAGE_SECTION_RE = re.compile(
    r"---\s*Page\s+(\d+)\s*---\s*(.*?)(?=(?:---\s*Page\s+\d+\s*---)|\Z)",
    re.DOTALL,
)
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_MD_DATE_RE = re.compile(r"(?m)^(\d{2})\.(\d{2})\s+(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b")


@dataclass(frozen=True)
class SummaryEvalPage:
    """One OCR'd page inside a notebook fixture."""

    page_index: int
    page_id: str
    text_content: str


@dataclass(frozen=True)
class SummaryEvalFact:
    """Expected factual checkpoint inside a notebook summary."""

    id: str
    region: str
    expected_date: str
    expected_page: int
    keywords: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class SummaryEvalAppendUpdate:
    """Trailing page append update scenario."""

    description: str
    pages: tuple[SummaryEvalPage, ...]
    expected_facts: tuple[SummaryEvalFact, ...]


@dataclass(frozen=True)
class SummaryEvalMidEditUpdate:
    """Mid-notebook single-page edit scenario."""

    description: str
    page_index: int
    page_id: str
    text_content: str
    expected_facts: tuple[SummaryEvalFact, ...]


@dataclass(frozen=True)
class SummaryEvalIncrementalUpdates:
    """Optional incremental update scenarios for a notebook."""

    append: SummaryEvalAppendUpdate | None = None
    mid_edit: SummaryEvalMidEditUpdate | None = None


@dataclass(frozen=True)
class SummaryEvalNotebook:
    """A large-notebook summarization fixture with ground-truth expectations."""

    file_name: str
    custom_type: str = "default"
    description: str = ""
    pages: tuple[SummaryEvalPage, ...] = ()
    expected_facts: tuple[SummaryEvalFact, ...] = ()
    incremental_updates: SummaryEvalIncrementalUpdates | None = None


@dataclass(frozen=True)
class SummaryEvalDataset:
    """Declarative large-notebook summarization evaluation dataset."""

    name: str
    description: str
    notebooks: tuple[SummaryEvalNotebook, ...]


@dataclass
class SummaryCallTrace:
    """Telemetry for a single `SummaryModel.summarize` invocation."""

    call_no: int
    prompt_chars: int
    elapsed_seconds: float
    segments_returned: int


@dataclass
class SummaryFactResult:
    """Scoring result for one expected fact checkpoint."""

    fact_id: str
    region: str
    expected_date: str
    expected_page: int
    matched_keywords: bool
    matched_date: bool
    matched_page: bool
    matched_segment_date_range: str | None = None


@dataclass
class SummaryIncrementalResult:
    """Telemetry and recall for one incremental update pass."""

    kind: str
    llm_calls: int
    prompt_chars: int
    elapsed_seconds: float
    fact_recall: float
    date_accuracy: float
    page_ref_accuracy: float
    fact_results: list[SummaryFactResult] = field(default_factory=list)


@dataclass
class SummaryNotebookMetrics:
    """Full evaluation metrics for one notebook."""

    file_name: str
    total_pages: int
    non_blank_pages: int
    transcript_chars: int
    summary_chars: int
    compression_ratio: float
    segment_count: int
    duplicate_date_range_count: int
    llm_calls: int
    total_prompt_chars: int
    elapsed_seconds: float
    fact_recall: float
    date_accuracy: float
    page_ref_accuracy: float
    region_recall: dict[str, float] = field(default_factory=dict)
    fact_results: list[SummaryFactResult] = field(default_factory=list)
    call_traces: list[SummaryCallTrace] = field(default_factory=list)
    incremental_results: list[SummaryIncrementalResult] = field(default_factory=list)
    rendered_markdown: str = ""


@dataclass
class SummaryEvalReport:
    """Aggregate report across all evaluated notebooks."""

    dataset_name: str
    target: str
    config: dict[str, Any]
    notebooks: list[SummaryNotebookMetrics]
    overall_fact_recall: float
    overall_date_accuracy: float
    overall_page_ref_accuracy: float
    overall_region_recall: dict[str, float]
    total_llm_calls: int
    total_prompt_chars: int
    total_elapsed_seconds: float


class _TracingSummaryModel(SummaryModel):
    """Wraps a `SummaryModel` to record per-call latency, prompt size, and segment count."""

    def __init__(self, inner: SummaryModel) -> None:
        self._inner = inner
        self.traces: list[SummaryCallTrace] = []

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def reset_traces(self) -> None:
        self.traces = []

    async def summarize(self, prompt: str) -> SummaryResponse:
        start = time.perf_counter()
        response = await self._inner.summarize(prompt)
        elapsed = time.perf_counter() - start
        self.traces.append(
            SummaryCallTrace(
                call_no=len(self.traces) + 1,
                prompt_chars=len(prompt),
                elapsed_seconds=round(elapsed, 3),
                segments_returned=len(response.segments),
            )
        )
        return response


_METADATA_PREFIXES = (
    "Notebook Filename:",
    "Notebook Created:",
    "Page ID:",
    "Page Date (Inferred):",
    "Keywords:",
)
_INFERRED_DATE_RE = re.compile(r"Page Date \(Inferred\):\s*(20\d{2}-\d{2}-\d{2})")


class DeterministicFakeSummaryModel(SummaryModel):
    """Offline deterministic `SummaryModel` for CI/smoke harness verification.

    Parses `--- Page N ---` sections from the transcript prompt and emits one
    segment per page carrying its inferred ISO date and content lines.
    """

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return "fake-deterministic-summary"

    async def summarize(self, prompt: str) -> SummaryResponse:
        prefix, _, transcript = prompt.partition("TRANSCRIPT:")
        if not transcript:
            transcript = prompt
            prefix = ""
        segments: list[SummarySegment] = []
        last_date: str | None = None
        if "PRIOR CONTEXT" in prefix:
            prior_dates = _ISO_DATE_RE.findall(
                prefix.split("PRIOR CONTEXT", maxsplit=1)[1]
            )
            if prior_dates:
                last_date = prior_dates[-1]
        for match in _PAGE_SECTION_RE.finditer(transcript):
            page_num = int(match.group(1))
            raw_body = match.group(2).strip()
            inferred_match = _INFERRED_DATE_RE.search(raw_body)
            content_lines = [
                ln.strip()
                for ln in raw_body.splitlines()
                if ln.strip() and not ln.strip().startswith(_METADATA_PREFIXES)
            ]
            content_text = "\n".join(content_lines)
            iso_dates = _ISO_DATE_RE.findall(content_text)
            md_matches = _MD_DATE_RE.findall(content_text)
            if md_matches:
                iso_dates = list(
                    dict.fromkeys(iso_dates + [f"2026-{m}-{d}" for m, d in md_matches])
                )
            if not iso_dates and inferred_match:
                iso_dates = [inferred_match.group(1)]
            if iso_dates:
                last_date = iso_dates[-1]
            date_range = iso_dates[0] if iso_dates else (last_date or "Unknown Date")
            extracted = list(dict.fromkeys(iso_dates)) or (
                [date_range] if date_range != "Unknown Date" else []
            )
            bullet_text = "\n".join(
                f"- {ln.lstrip('•X><o- ').strip()}" for ln in content_lines
            )
            segments.append(
                SummarySegment(
                    date_range=date_range,
                    summary=bullet_text or "(empty)",
                    extracted_dates=extracted,
                    page_refs=[page_num],
                )
            )
        return SummaryResponse(segments=segments)


def _parse_keywords(raw: list[Any]) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for item in raw:
        if isinstance(item, str):
            groups.append((item.lower(),))
        elif isinstance(item, list):
            groups.append(tuple(str(v).lower() for v in item if str(v).strip()))
    return tuple(g for g in groups if g)


def _parse_fact(raw: dict[str, Any]) -> SummaryEvalFact:
    return SummaryEvalFact(
        id=str(raw["id"]),
        region=str(raw.get("region", "general")),
        expected_date=str(raw["expected_date"]),
        expected_page=int(raw["expected_page"]),
        keywords=_parse_keywords(raw.get("keywords", [])),
    )


def _parse_page(raw: dict[str, Any]) -> SummaryEvalPage:
    return SummaryEvalPage(
        page_index=int(raw["page_index"]),
        page_id=str(raw["page_id"]),
        text_content=str(raw.get("text_content", "")),
    )


def load_summary_eval_dataset(path: Path) -> SummaryEvalDataset:
    """Load a declarative `SummaryEvalDataset` from YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    notebooks: list[SummaryEvalNotebook] = []
    for nb in raw.get("notebooks", []):
        pages = tuple(_parse_page(p) for p in nb.get("pages", []))
        facts = tuple(_parse_fact(f) for f in nb.get("expected_facts", []))
        inc_raw = nb.get("incremental_updates")
        inc: SummaryEvalIncrementalUpdates | None = None
        if isinstance(inc_raw, dict):
            append_obj: SummaryEvalAppendUpdate | None = None
            if app := inc_raw.get("append"):
                append_obj = SummaryEvalAppendUpdate(
                    description=str(app.get("description", "")),
                    pages=tuple(_parse_page(p) for p in app.get("pages", [])),
                    expected_facts=tuple(
                        _parse_fact(f) for f in app.get("expected_facts", [])
                    ),
                )
            mid_obj: SummaryEvalMidEditUpdate | None = None
            if mid := inc_raw.get("mid_edit"):
                mid_obj = SummaryEvalMidEditUpdate(
                    description=str(mid.get("description", "")),
                    page_index=int(mid["page_index"]),
                    page_id=str(mid["page_id"]),
                    text_content=str(mid.get("text_content", "")),
                    expected_facts=tuple(
                        _parse_fact(f) for f in mid.get("expected_facts", [])
                    ),
                )
            inc = SummaryEvalIncrementalUpdates(append=append_obj, mid_edit=mid_obj)
        notebooks.append(
            SummaryEvalNotebook(
                file_name=str(nb["file_name"]),
                custom_type=str(nb.get("custom_type", "default")),
                description=str(nb.get("description", "")),
                pages=pages,
                expected_facts=facts,
                incremental_updates=inc,
            )
        )
    return SummaryEvalDataset(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")),
        notebooks=tuple(notebooks),
    )


def _matches_all_groups(text_lower: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(any(syn in text_lower for syn in group) for group in groups)


def _score_facts(
    segments: list[dict[str, Any]],
    rendered_markdown: str,
    facts: tuple[SummaryEvalFact, ...],
) -> tuple[list[SummaryFactResult], float, float, float, dict[str, float]]:
    results: list[SummaryFactResult] = []
    full_lower = rendered_markdown.lower()

    for fact in facts:
        best_seg: dict[str, Any] | None = None
        best_score = -1
        for seg in segments:
            seg_text = f"{seg.get('date_range', '')}\n{seg.get('summary', '')}".lower()
            if _matches_all_groups(seg_text, fact.keywords):
                extracted = [str(d) for d in (seg.get("extracted_dates") or [])]
                date_hit = fact.expected_date in extracted or fact.expected_date in str(
                    seg.get("date_range", "")
                )
                page_refs = [int(p) for p in (seg.get("page_refs") or [])]
                page_hit = fact.expected_page in page_refs
                score = int(date_hit) + int(page_hit)
                if score > best_score:
                    best_score = score
                    best_seg = seg

        if best_seg is not None:
            extracted = [str(d) for d in (best_seg.get("extracted_dates") or [])]
            page_refs = [int(p) for p in (best_seg.get("page_refs") or [])]
            matched_kw = True
            matched_date = fact.expected_date in extracted or fact.expected_date in str(
                best_seg.get("date_range", "")
            )
            matched_page = fact.expected_page in page_refs
            matched_range = str(best_seg.get("date_range", ""))
        else:
            matched_kw = _matches_all_groups(full_lower, fact.keywords)
            matched_date = False
            matched_page = False
            matched_range = None

        results.append(
            SummaryFactResult(
                fact_id=fact.id,
                region=fact.region,
                expected_date=fact.expected_date,
                expected_page=fact.expected_page,
                matched_keywords=matched_kw,
                matched_date=matched_date,
                matched_page=matched_page,
                matched_segment_date_range=matched_range,
            )
        )

    total = len(results)
    if total == 0:
        return results, 1.0, 1.0, 1.0, {}

    fact_recall = sum(1 for r in results if r.matched_keywords) / total
    date_accuracy = sum(1 for r in results if r.matched_date) / total
    page_ref_accuracy = sum(1 for r in results if r.matched_page) / total

    by_region: dict[str, list[SummaryFactResult]] = {}
    for r in results:
        by_region.setdefault(r.region, []).append(r)
    region_recall = {
        region: round(sum(1 for r in items if r.matched_keywords) / len(items), 4)
        for region, items in sorted(by_region.items())
    }
    return (
        results,
        round(fact_recall, 4),
        round(date_accuracy, 4),
        round(page_ref_accuracy, 4),
        region_recall,
    )


def _count_duplicate_date_ranges(segments: list[dict[str, Any]]) -> int:
    counts = Counter(
        str(seg.get("date_range", "")).strip().lower()
        for seg in segments
        if str(seg.get("date_range", "")).strip().lower() not in ("", "unknown date")
    )
    return sum(c - 1 for c in counts.values() if c > 1)


async def run_summary_eval(
    dataset: SummaryEvalDataset,
    model: SummaryModel,
    *,
    target_label: str,
    summary_config: SummaryConfig | None = None,
    notebook_filter: set[str] | None = None,
    run_incremental: bool = True,
    export_dir: Path | None = None,
) -> SummaryEvalReport:
    """Run `SummaryModule` against every notebook in `dataset` and score results."""
    cfg = summary_config if summary_config is not None else SummaryConfig()
    tracing_model = _TracingSummaryModel(model)
    notebook_reports: list[SummaryNotebookMetrics] = []

    with tempfile.TemporaryDirectory(prefix="supernote_summary_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_url = f"sqlite+aiosqlite:///{tmp_path / 'eval.db'}"
        session_manager = DatabaseSessionManager(db_url)
        await session_manager.create_all_tables()

        try:
            event_bus = LocalEventBus()
            blob_storage = LocalBlobStorage(tmp_path / "blobs")
            coordination_service = SqliteCoordinationService(session_manager)
            user_service = UserService(
                AuthConfig(),
                coordination_service,
                session_manager,
            )
            file_service = FileService(
                storage_root=tmp_path / "files",
                blob_storage=blob_storage,
                user_service=user_service,
                session_manager=session_manager,
                event_bus=event_bus,
            )
            summary_service = SummaryService(
                user_service=user_service,
                session_manager=session_manager,
                event_bus=event_bus,
            )
            module = SummaryModule(
                file_service=file_service,
                summary_service=summary_service,
                summary_model=tracing_model,
                config=cfg,
            )

            user_id = 1001
            user_email = "eval@supernote.local"
            async with session_manager.session() as session:
                session.add(UserDO(id=user_id, email=user_email, password_md5="eval"))
                await session.commit()

            for idx, nb in enumerate(dataset.notebooks, start=1):
                if notebook_filter and nb.file_name not in notebook_filter:
                    continue

                file_id = 10_000 + idx
                async with session_manager.session() as session:
                    session.add(
                        UserFileDO(
                            id=file_id,
                            user_id=user_id,
                            storage_key=f"eval_{file_id}",
                            file_name=nb.file_name,
                            directory_id=0,
                            is_active="Y",
                            is_folder="N",
                        )
                    )
                    for page in nb.pages:
                        session.add(
                            NotePageContentDO(
                                file_id=file_id,
                                page_index=page.page_index,
                                page_id=page.page_id,
                                content_hash=f"h_{file_id}_{page.page_index}_v1",
                                text_content=page.text_content,
                            )
                        )
                    await session.commit()

                tracing_model.reset_traces()
                t0 = time.perf_counter()
                await module.process(file_id, session_manager)
                elapsed = round(time.perf_counter() - t0, 3)

                summary_item = await summary_service.get_summary_by_uuid(
                    user_email, get_summary_id(user_id, file_id)
                )
                rendered_md = (summary_item.content or "") if summary_item else ""
                segments: list[dict[str, Any]] = []
                if summary_item and summary_item.metadata:
                    meta = json.loads(summary_item.metadata)
                    segments = list(meta.get(METADATA_SEGMENTS, []))

                (
                    fact_results,
                    fact_recall,
                    date_acc,
                    page_acc,
                    region_recall,
                ) = _score_facts(segments, rendered_md, nb.expected_facts)
                initial_traces = list(tracing_model.traces)

                inc_results: list[SummaryIncrementalResult] = []
                if run_incremental and nb.incremental_updates is not None:
                    if app := nb.incremental_updates.append:
                        async with session_manager.session() as session:
                            for page in app.pages:
                                session.add(
                                    NotePageContentDO(
                                        file_id=file_id,
                                        page_index=page.page_index,
                                        page_id=page.page_id,
                                        content_hash=f"h_{file_id}_{page.page_index}_append",
                                        text_content=page.text_content,
                                    )
                                )
                            await session.commit()
                        tracing_model.reset_traces()
                        inc_t0 = time.perf_counter()
                        await module.process(file_id, session_manager)
                        inc_elapsed = round(time.perf_counter() - inc_t0, 3)
                        updated = await summary_service.get_summary_by_uuid(
                            user_email, get_summary_id(user_id, file_id)
                        )
                        upd_md = (updated.content or "") if updated else ""
                        upd_segs = (
                            list(
                                json.loads(updated.metadata).get(METADATA_SEGMENTS, [])
                            )
                            if updated and updated.metadata
                            else []
                        )
                        app_facts, app_rec, app_date, app_page, _ = _score_facts(
                            upd_segs, upd_md, app.expected_facts
                        )
                        inc_results.append(
                            SummaryIncrementalResult(
                                kind="append",
                                llm_calls=len(tracing_model.traces),
                                prompt_chars=sum(
                                    t.prompt_chars for t in tracing_model.traces
                                ),
                                elapsed_seconds=inc_elapsed,
                                fact_recall=app_rec,
                                date_accuracy=app_date,
                                page_ref_accuracy=app_page,
                                fact_results=app_facts,
                            )
                        )

                    if mid := nb.incremental_updates.mid_edit:
                        async with session_manager.session() as session:
                            row = (
                                await session.execute(
                                    select(NotePageContentDO).where(
                                        NotePageContentDO.file_id == file_id,
                                        NotePageContentDO.page_id == mid.page_id,
                                    )
                                )
                            ).scalar_one()
                            row.text_content = mid.text_content
                            row.content_hash = f"h_{file_id}_{mid.page_index}_edited"
                            await session.commit()
                        tracing_model.reset_traces()
                        inc_t0 = time.perf_counter()
                        await module.process(file_id, session_manager)
                        inc_elapsed = round(time.perf_counter() - inc_t0, 3)
                        updated = await summary_service.get_summary_by_uuid(
                            user_email, get_summary_id(user_id, file_id)
                        )
                        upd_md = (updated.content or "") if updated else ""
                        upd_segs = (
                            list(
                                json.loads(updated.metadata).get(METADATA_SEGMENTS, [])
                            )
                            if updated and updated.metadata
                            else []
                        )
                        mid_facts, mid_rec, mid_date, mid_page, _ = _score_facts(
                            upd_segs, upd_md, mid.expected_facts
                        )
                        inc_results.append(
                            SummaryIncrementalResult(
                                kind="mid_edit",
                                llm_calls=len(tracing_model.traces),
                                prompt_chars=sum(
                                    t.prompt_chars for t in tracing_model.traces
                                ),
                                elapsed_seconds=inc_elapsed,
                                fact_recall=mid_rec,
                                date_accuracy=mid_date,
                                page_ref_accuracy=mid_page,
                                fact_results=mid_facts,
                            )
                        )

                transcript_chars = sum(
                    len(p.text_content) for p in nb.pages if p.text_content.strip()
                )
                summary_chars = len(rendered_md)
                compression_ratio = (
                    round(summary_chars / transcript_chars, 3)
                    if transcript_chars > 0
                    else 0.0
                )

                notebook_reports.append(
                    SummaryNotebookMetrics(
                        file_name=nb.file_name,
                        total_pages=len(nb.pages),
                        non_blank_pages=sum(
                            1 for p in nb.pages if p.text_content.strip()
                        ),
                        transcript_chars=transcript_chars,
                        summary_chars=summary_chars,
                        compression_ratio=compression_ratio,
                        segment_count=len(segments),
                        duplicate_date_range_count=_count_duplicate_date_ranges(
                            segments
                        ),
                        llm_calls=len(initial_traces),
                        total_prompt_chars=sum(t.prompt_chars for t in initial_traces),
                        elapsed_seconds=elapsed,
                        fact_recall=fact_recall,
                        date_accuracy=date_acc,
                        page_ref_accuracy=page_acc,
                        region_recall=region_recall,
                        fact_results=fact_results,
                        call_traces=initial_traces,
                        incremental_results=inc_results,
                        rendered_markdown=rendered_md,
                    )
                )
        finally:
            await session_manager.close()

    all_facts = [r for nb in notebook_reports for r in nb.fact_results]
    total_facts = len(all_facts)
    overall_fact_recall = (
        round(sum(1 for r in all_facts if r.matched_keywords) / total_facts, 4)
        if total_facts
        else 1.0
    )
    overall_date_acc = (
        round(sum(1 for r in all_facts if r.matched_date) / total_facts, 4)
        if total_facts
        else 1.0
    )
    overall_page_acc = (
        round(sum(1 for r in all_facts if r.matched_page) / total_facts, 4)
        if total_facts
        else 1.0
    )
    by_region: dict[str, list[SummaryFactResult]] = {}
    for r in all_facts:
        by_region.setdefault(r.region, []).append(r)
    overall_region_recall = {
        reg: round(sum(1 for r in items if r.matched_keywords) / len(items), 4)
        for reg, items in sorted(by_region.items())
    }

    report = SummaryEvalReport(
        dataset_name=dataset.name,
        target=target_label,
        config=cfg.to_dict(),
        notebooks=notebook_reports,
        overall_fact_recall=overall_fact_recall,
        overall_date_accuracy=overall_date_acc,
        overall_page_ref_accuracy=overall_page_acc,
        overall_region_recall=overall_region_recall,
        total_llm_calls=sum(nb.llm_calls for nb in notebook_reports),
        total_prompt_chars=sum(nb.total_prompt_chars for nb in notebook_reports),
        total_elapsed_seconds=round(
            sum(nb.elapsed_seconds for nb in notebook_reports), 3
        ),
    )

    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "report.md").write_text(
            format_markdown_report(report), encoding="utf-8"
        )
        (export_dir / "report.json").write_text(
            json.dumps(asdict(report), indent=2), encoding="utf-8"
        )
        for nb in notebook_reports:
            stem = Path(nb.file_name).stem
            (export_dir / f"{stem}.summary.md").write_text(
                nb.rendered_markdown, encoding="utf-8"
            )

    return report


def format_markdown_report(report: SummaryEvalReport) -> str:
    """Render a human-readable Markdown report from a `SummaryEvalReport`."""
    lines: list[str] = [
        f"# Summary Evaluation Report — `{report.dataset_name}`",
        "",
        f"- **Target**: `{report.target}`",
        f"- **Config**: `{json.dumps(report.config)}`",
        f"- **Overall Fact Recall**: {report.overall_fact_recall:.1%}",
        f"- **Overall Date Accuracy**: {report.overall_date_accuracy:.1%}",
        f"- **Overall Page-Ref Accuracy**: {report.overall_page_ref_accuracy:.1%}",
        f"- **Total Initial LLM Calls**: {report.total_llm_calls} ({report.total_prompt_chars:,} prompt chars, {report.total_elapsed_seconds:.2f}s)",
        "",
        "## Per-Region Recall",
        "",
        "| Region | Fact Recall |",
        "| :--- | ---: |",
    ]
    for region, recall in report.overall_region_recall.items():
        lines.append(f"| `{region}` | {recall:.1%} |")

    lines.extend(
        [
            "",
            "## Per-Notebook Metrics",
            "",
            "| Notebook | Pages (Non-Blank) | Segments | Dup Dates | Compression | LLM Calls | Prompt Chars | Fact Recall | Date Acc | Page Ref Acc | Elapsed |",
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for nb in report.notebooks:
        lines.append(
            f"| `{nb.file_name}` | {nb.total_pages} ({nb.non_blank_pages}) | "
            f"{nb.segment_count} | {nb.duplicate_date_range_count} | "
            f"{nb.compression_ratio:.0%} | "
            f"{nb.llm_calls} | {nb.total_prompt_chars:,} | "
            f"{nb.fact_recall:.1%} | {nb.date_accuracy:.1%} | "
            f"{nb.page_ref_accuracy:.1%} | {nb.elapsed_seconds:.2f}s |"
        )

    inc_rows = [
        (nb.file_name, inc) for nb in report.notebooks for inc in nb.incremental_results
    ]
    if inc_rows:
        lines.extend(
            [
                "",
                "## Incremental Update Telemetry",
                "",
                "| Notebook | Update | LLM Calls | Prompt Chars | Fact Recall | Date Acc | Page Ref Acc | Elapsed |",
                "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for fname, inc in inc_rows:
            lines.append(
                f"| `{fname}` | `{inc.kind}` | {inc.llm_calls} | {inc.prompt_chars:,} | "
                f"{inc.fact_recall:.1%} | {inc.date_accuracy:.1%} | "
                f"{inc.page_ref_accuracy:.1%} | {inc.elapsed_seconds:.2f}s |"
            )

    missed = [
        (nb.file_name, r)
        for nb in report.notebooks
        for r in nb.fact_results
        if not (r.matched_keywords and r.matched_date and r.matched_page)
    ]
    if missed:
        lines.extend(
            [
                "",
                "## Partial / Missed Checkpoints",
                "",
                "| Notebook | Fact ID | Region | Keywords | Date | Page Ref |",
                "| :--- | :--- | :--- | :---: | :---: | :---: |",
            ]
        )
        for fname, r in missed:
            lines.append(
                f"| `{fname}` | `{r.fact_id}` | `{r.region}` | "
                f"{'OK' if r.matched_keywords else 'MISS'} | "
                f"{'OK' if r.matched_date else 'MISS'} | "
                f"{'OK' if r.matched_page else 'MISS'} |"
            )

    return "\n".join(lines) + "\n"
