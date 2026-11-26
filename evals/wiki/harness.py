"""Repeatable LLM Wiki backfill evaluation harness and quality scorer."""

from __future__ import annotations

import json
import re
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

import supernote.server.db.models  # noqa: F401
from supernote.models.wiki import WikiLintIssueDTO, WikiPageDTO
from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.components.events.service import EventLogService
from supernote.server.components.wiki.compiler import WikiCompilerWorker
from supernote.server.components.wiki.config import WikiConfig
from supernote.server.components.wiki.export import WikiExportService
from supernote.server.components.wiki.service import WikiService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.metrics import AIStage
from supernote.server.services.coordination import SqliteCoordinationService

__all__ = [
    "DeterministicFakeWikiModel",
    "WikiEvalBatchTrace",
    "WikiEvalConceptExpectation",
    "WikiEvalDataset",
    "WikiEvalFactExpectation",
    "WikiEvalMetrics",
    "WikiEvalNotebook",
    "WikiEvalPage",
    "WikiEvalPageSummary",
    "WikiEvalReport",
    "WikiEvalTask",
    "format_markdown_report",
    "load_wiki_eval_dataset",
    "run_wiki_eval",
    "seed_eval_database",
]


@dataclass(frozen=True)
class WikiEvalPage:
    """One OCR'd page inside a notebook fixture."""

    page_index: int
    page_id: str
    text_content: str


@dataclass(frozen=True)
class WikiEvalNotebook:
    """A notebook fixture with zero or more OCR'd pages."""

    file_name: str
    description: str = ""
    pages: tuple[WikiEvalPage, ...] = ()


@dataclass(frozen=True)
class WikiEvalTask:
    """A schedule task fixture seeded alongside notebooks."""

    task_id: str
    title: str
    detail: str = ""
    status: str = "needsAction"
    importance: str = "normal"


@dataclass(frozen=True)
class WikiEvalConceptExpectation:
    """Expected recurring project, entity, or topic in the compiled wiki."""

    name: str
    kind: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class WikiEvalFactExpectation:
    """Expected evolved decision or factual detail captured in wiki prose."""

    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class WikiEvalDataset:
    """Declarative wiki backfill evaluation dataset."""

    name: str
    description: str
    notebooks: tuple[WikiEvalNotebook, ...]
    tasks: tuple[WikiEvalTask, ...] = ()
    expected_concepts: tuple[WikiEvalConceptExpectation, ...] = ()
    expected_facts: tuple[WikiEvalFactExpectation, ...] = ()


@dataclass
class WikiEvalBatchTrace:
    """Telemetry for one backfill batch execution."""

    batch_no: int
    events_processed: int
    pages_updated: int
    skipped_policy_pages: int
    lint_issues_open: int
    status: str
    elapsed_seconds: float


@dataclass
class WikiEvalPageSummary:
    """Compact summary of one compiled wiki page for reporting."""

    slug: str
    title: str
    page_kind: str
    summary: str
    body_chars: int
    outbound_links: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    source_ref_count: int = 0


@dataclass
class WikiEvalMetrics:
    """Quantitative quality metrics for a wiki backfill run."""

    total_notebooks: int
    transcribed_notebooks: int
    batches_run: int
    elapsed_seconds: float
    total_pages: int
    pages_by_kind: dict[str, int]
    non_source_pages: int
    non_source_ratio: float
    has_index_page: bool
    avg_outbound_links: float
    avg_body_chars: float
    open_lint_total: int
    open_lint_by_type: dict[str, int]
    concept_recall_synthesized: float
    concept_recall_all: float
    matched_concepts_synthesized: list[str]
    missed_concepts_synthesized: list[str]
    fact_recall: float
    matched_facts: list[str]
    missed_facts: list[str]
    prose_source_leaks: int = 0


@dataclass
class WikiEvalReport:
    """Complete evaluation report returned by `run_wiki_eval`."""

    dataset_name: str
    target: str
    max_files_per_batch: int
    max_pages_per_batch: int
    ran_semantic_lint: bool
    metrics: WikiEvalMetrics
    batches: list[WikiEvalBatchTrace]
    pages: list[WikiEvalPageSummary]
    lint_issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize report to a JSON-compatible dictionary."""
        return asdict(self)


def load_wiki_eval_dataset(path: Path) -> WikiEvalDataset:
    """Load and validate a `WikiEvalDataset` from a YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"Expected YAML mapping in {path}")

    notebooks: list[WikiEvalNotebook] = []
    for nb in raw.get("notebooks") or []:
        pages = tuple(
            WikiEvalPage(
                page_index=int(p["page_index"]),
                page_id=str(p["page_id"]),
                text_content=str(p["text_content"]),
            )
            for p in (nb.get("pages") or [])
        )
        notebooks.append(
            WikiEvalNotebook(
                file_name=str(nb["file_name"]),
                description=str(nb.get("description") or ""),
                pages=pages,
            )
        )

    tasks = tuple(
        WikiEvalTask(
            task_id=str(t["task_id"]),
            title=str(t["title"]),
            detail=str(t.get("detail") or ""),
            status=str(t.get("status") or "needsAction"),
            importance=str(t.get("importance") or "normal"),
        )
        for t in (raw.get("tasks") or [])
    )

    exp = raw.get("expectations") or {}
    concepts = tuple(
        WikiEvalConceptExpectation(
            name=str(c["name"]),
            kind=str(c.get("kind") or "topic"),
            keywords=tuple(str(k).lower() for k in (c.get("keywords") or [])),
        )
        for c in (exp.get("concepts") or [])
    )
    facts = tuple(
        WikiEvalFactExpectation(
            name=str(f["name"]),
            keywords=tuple(str(k).lower() for k in (f.get("keywords") or [])),
        )
        for f in (exp.get("facts") or [])
    )

    return WikiEvalDataset(
        name=str(raw.get("name") or path.stem),
        description=str(raw.get("description") or ""),
        notebooks=tuple(notebooks),
        tasks=tasks,
        expected_concepts=concepts,
        expected_facts=facts,
    )


class DeterministicFakeWikiModel(TextGenerationModel):
    """Offline deterministic `TextGenerationModel` for smoke-testing the eval harness."""

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return "deterministic"

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        _ = (response_schema, stage)
        if schema_name == "wiki_lint_report":
            return {"issues": []}

        # Extract notebook file paths and short source_id handles from <source_diff>.
        diff_block = prompt.rsplit("<source_diff>", maxsplit=1)[-1].split(
            "</source_diff>", maxsplit=1
        )[0]
        file_handles: dict[str, str] = {}
        try:
            diff_events = json.loads(diff_block.strip())
        except json.JSONDecodeError:
            diff_events = []
        for ev in diff_events if isinstance(diff_events, list) else []:
            if not isinstance(ev, Mapping):
                continue
            payload = ev.get("payload")
            fp = (
                str(payload.get("file_path") or "")
                if isinstance(payload, Mapping)
                else ""
            )
            sid = str(ev.get("source_id") or "")
            if fp and fp not in file_handles:
                file_handles[fp] = sid or "page01"

        page_ops: list[dict[str, Any]] = []
        for fp, handle in list(file_handles.items())[:5]:
            stem = Path(fp).stem
            slug_name = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
            page_ops.append(
                {
                    "slug": f"sources/{slug_name}",
                    "title": stem.replace("_", " "),
                    "page_kind": "source_digest",
                    "summary": f"Digest compiled from {fp}",
                    "body_md": f"## {stem.replace('_', ' ')}\n\nCompiled from `{fp}`.",
                    "source_refs": [
                        {
                            "source_type": "note_page",
                            "source_key": handle,
                        }
                    ],
                }
            )
        return {"page_ops": page_ops, "lint_proposals": []}


async def seed_eval_database(
    session_manager: DatabaseSessionManager,
    dataset: WikiEvalDataset,
    *,
    user_id: int = 1,
) -> None:
    """Seed dataset notebooks, OCR pages, and schedule tasks into `session_manager`."""
    now_ms = int(time.time() * 1000)
    async with session_manager.session() as session:
        for idx, nb in enumerate(dataset.notebooks, start=1):
            file_id = 1000 + idx
            session.add(
                UserFileDO(
                    id=file_id,
                    user_id=user_id,
                    directory_id=0,
                    file_name=nb.file_name,
                    is_folder="N",
                    is_active="Y",
                    create_time=now_ms + idx * 1000,
                    update_time=now_ms + idx * 1000,
                )
            )
            for page in nb.pages:
                session.add(
                    NotePageContentDO(
                        file_id=file_id,
                        page_index=page.page_index,
                        page_id=page.page_id,
                        text_content=page.text_content,
                        create_time=now_ms + idx * 1000,
                        update_time=now_ms + idx * 1000,
                    )
                )

        for idx, task in enumerate(dataset.tasks, start=1):
            session.add(
                ScheduleTaskDO(
                    user_id=user_id,
                    task_id=task.task_id,
                    title=task.title,
                    detail=task.detail,
                    status=task.status,
                    importance=task.importance,
                    update_time=now_ms + idx * 1000,
                )
            )
        await session.commit()


def _matches_any_keyword(haystack_lower: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in haystack_lower for kw in keywords)


def _compute_metrics(
    *,
    dataset: WikiEvalDataset,
    pages: list[WikiPageDTO],
    lint_issues: list[WikiLintIssueDTO],
    batches: list[WikiEvalBatchTrace],
    elapsed_seconds: float,
) -> WikiEvalMetrics:
    pages_by_kind = dict(sorted(Counter(p.page_kind for p in pages).items()))
    total_pages = len(pages)
    non_source = [p for p in pages if p.page_kind != "source_digest"]
    non_source_ratio = (len(non_source) / total_pages) if total_pages else 0.0
    has_index = any(p.page_kind == "index" or p.slug == "index" for p in pages)
    avg_outbound = (
        sum(len(p.outbound_links) for p in pages) / total_pages if total_pages else 0.0
    )
    avg_body = sum(len(p.body_md) for p in pages) / total_pages if total_pages else 0.0
    lint_by_type = dict(sorted(Counter(i.issue_type for i in lint_issues).items()))

    synth_corpus = "\n".join(
        f"{p.slug} {p.title} {p.summary} {' '.join(p.aliases)}".lower()
        for p in non_source
    )
    all_corpus = "\n".join(
        f"{p.slug} {p.title} {p.summary} {' '.join(p.aliases)} {p.body_md}".lower()
        for p in pages
    )

    matched_synth: list[str] = []
    missed_synth: list[str] = []
    matched_all_count = 0
    for concept in dataset.expected_concepts:
        if _matches_any_keyword(synth_corpus, concept.keywords):
            matched_synth.append(concept.name)
        else:
            missed_synth.append(concept.name)
        if _matches_any_keyword(all_corpus, concept.keywords):
            matched_all_count += 1

    n_concepts = len(dataset.expected_concepts)
    concept_recall_synth = (len(matched_synth) / n_concepts) if n_concepts else 1.0
    concept_recall_all = (matched_all_count / n_concepts) if n_concepts else 1.0

    matched_facts: list[str] = []
    missed_facts: list[str] = []
    for fact in dataset.expected_facts:
        if _matches_any_keyword(all_corpus, fact.keywords):
            matched_facts.append(fact.name)
        else:
            missed_facts.append(fact.name)
    n_facts = len(dataset.expected_facts)
    fact_recall = (len(matched_facts) / n_facts) if n_facts else 1.0

    prose_leak_re = re.compile(
        r"\b(?:note_page|source_notes|schedule_task):\S+"
        r"|\bP20\d{12}[A-Za-z0-9]*\b"
        r"|\[\[(?:page|task)\d{2,}\]\]"
        r"|\((?:page|task)\d{2,}\)"
    )
    prose_source_leaks = sum(
        1
        for p in pages
        if prose_leak_re.search(f"{p.summary}\n{p.body_md}") is not None
    )

    transcribed = sum(1 for nb in dataset.notebooks if nb.pages)
    return WikiEvalMetrics(
        total_notebooks=len(dataset.notebooks),
        transcribed_notebooks=transcribed,
        batches_run=len(batches),
        elapsed_seconds=round(elapsed_seconds, 2),
        total_pages=total_pages,
        pages_by_kind=pages_by_kind,
        non_source_pages=len(non_source),
        non_source_ratio=round(non_source_ratio, 3),
        has_index_page=has_index,
        avg_outbound_links=round(avg_outbound, 2),
        avg_body_chars=round(avg_body, 1),
        open_lint_total=len(lint_issues),
        open_lint_by_type=lint_by_type,
        concept_recall_synthesized=round(concept_recall_synth, 3),
        concept_recall_all=round(concept_recall_all, 3),
        matched_concepts_synthesized=matched_synth,
        missed_concepts_synthesized=missed_synth,
        fact_recall=round(fact_recall, 3),
        matched_facts=matched_facts,
        missed_facts=missed_facts,
        prose_source_leaks=prose_source_leaks,
    )


async def _export_eval_vault(
    export_dir: Path,
    wiki_service: WikiService,
    pages: list[WikiPageDTO],
    report: WikiEvalReport,
    *,
    user_id: int = 1,
) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    vault_dir = export_dir / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    exporter = WikiExportService(wiki_service)
    for page in pages:
        md = await exporter.export_page_markdown(user_id, page.slug)
        dest = vault_dir / f"{page.slug}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
    (export_dir / "report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    (export_dir / "report.md").write_text(
        format_markdown_report(report), encoding="utf-8"
    )


async def run_wiki_eval(
    dataset: WikiEvalDataset,
    text_model: TextGenerationModel,
    *,
    target_label: str | None = None,
    max_files_per_batch: int = 5,
    max_pages_per_batch: int = 5,
    run_semantic_lint: bool = False,
    export_dir: Path | None = None,
) -> WikiEvalReport:
    """Run multi-batch `WikiCompilerWorker.run_backfill` on an isolated ephemeral DB."""
    target = target_label or f"{text_model.provider}:{text_model.model_id}"
    user_id = 1

    with tempfile.TemporaryDirectory() as tmp_str:
        db_path = Path(tmp_str) / "wiki_eval.sqlite"
        session_manager = DatabaseSessionManager(f"sqlite+aiosqlite:///{db_path}")
        try:
            await session_manager.create_all_tables()

            await seed_eval_database(session_manager, dataset, user_id=user_id)

            event_bus = LocalEventBus()
            coord = SqliteCoordinationService(session_manager)
            event_log = EventLogService(session_manager, coord, event_bus)
            wiki_service = WikiService(session_manager)
            worker = WikiCompilerWorker(
                config=WikiConfig(
                    enabled=True,
                    auto_compile=False,
                    max_pages_per_batch=max_pages_per_batch,
                ),
                session_manager=session_manager,
                wiki_service=wiki_service,
                event_log_service=event_log,
                event_bus=event_bus,
                text_model=text_model,
            )

            t0 = time.monotonic()
            batches: list[WikiEvalBatchTrace] = []
            max_batches = max(1, len(dataset.notebooks) + 2)
            for batch_no in range(1, max_batches + 1):
                bt0 = time.monotonic()
                res = await worker.run_backfill(user_id, max_files=max_files_per_batch)
                bt_elapsed = round(time.monotonic() - bt0, 2)
                if res.events_processed == 0 and res.pages_updated == 0:
                    break
                batches.append(
                    WikiEvalBatchTrace(
                        batch_no=batch_no,
                        events_processed=res.events_processed,
                        pages_updated=res.pages_updated,
                        skipped_policy_pages=res.skipped_policy_pages,
                        lint_issues_open=res.lint_issues_open,
                        status=res.status,
                        elapsed_seconds=bt_elapsed,
                    )
                )
                if res.status == "paused":
                    break

            if run_semantic_lint:
                await worker.run_semantic_lint(user_id)

            elapsed = time.monotonic() - t0
            pages = await wiki_service.list_pages(user_id, limit=500)
            lint_issues = await wiki_service.list_lint_issues(user_id, status="open")
            metrics = _compute_metrics(
                dataset=dataset,
                pages=pages,
                lint_issues=lint_issues,
                batches=batches,
                elapsed_seconds=elapsed,
            )

            report = WikiEvalReport(
                dataset_name=dataset.name,
                target=target,
                max_files_per_batch=max_files_per_batch,
                max_pages_per_batch=max_pages_per_batch,
                ran_semantic_lint=run_semantic_lint,
                metrics=metrics,
                batches=batches,
                pages=[
                    WikiEvalPageSummary(
                        slug=p.slug,
                        title=p.title,
                        page_kind=p.page_kind,
                        summary=p.summary,
                        body_chars=len(p.body_md),
                        outbound_links=list(p.outbound_links),
                        backlinks=list(p.backlinks),
                        source_ref_count=len(p.source_refs),
                    )
                    for p in pages
                ],
                lint_issues=[
                    {
                        "issue_type": i.issue_type,
                        "severity": i.severity,
                        "description": i.description,
                    }
                    for i in lint_issues
                ],
            )

            if export_dir is not None:
                await _export_eval_vault(
                    export_dir, wiki_service, pages, report, user_id=user_id
                )
            return report
        finally:
            await session_manager.close()


def format_markdown_report(report: WikiEvalReport) -> str:
    """Format a `WikiEvalReport` into a concise Markdown summary."""
    m = report.metrics
    lines = [
        f"# Wiki Backfill Eval Report — `{report.target}`",
        "",
        f"- **Dataset**: `{report.dataset_name}` ({m.transcribed_notebooks}/{m.total_notebooks} OCR'd notebooks)",
        f"- **Settings**: `max_files_per_batch={report.max_files_per_batch}`, `max_pages_per_batch={report.max_pages_per_batch}`, `semantic_lint={report.ran_semantic_lint}`",
        f"- **Run**: {m.batches_run} batches in {m.elapsed_seconds:.2f}s",
        "",
        "## Quality Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total wiki pages | {m.total_pages} |",
        f"| Non-source synthesized pages | {m.non_source_pages} ({m.non_source_ratio * 100:.1f}%) |",
        f"| Has `index` hub page | {'Yes' if m.has_index_page else 'No'} |",
        f"| Avg outbound `[[wikilinks]]` / page | {m.avg_outbound_links:.2f} |",
        f"| Avg body length (chars) | {m.avg_body_chars:.1f} |",
        f"| Open lint issues | {m.open_lint_total} ({m.open_lint_by_type or 'none'}) |",
        f"| Prose source-ID leaks | {m.prose_source_leaks} |",
        f"| Concept recall (synthesized pages) | {m.concept_recall_synthesized * 100:.1f}% ({len(m.matched_concepts_synthesized)}/{len(m.matched_concepts_synthesized) + len(m.missed_concepts_synthesized)}) |",
        f"| Concept recall (all pages) | {m.concept_recall_all * 100:.1f}% |",
        f"| Evolved fact recall | {m.fact_recall * 100:.1f}% ({len(m.matched_facts)}/{len(m.matched_facts) + len(m.missed_facts)}) |",
        "",
        "## Pages by Kind",
        "",
    ]
    if m.pages_by_kind:
        for kind, count in m.pages_by_kind.items():
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(["", "## Concept & Fact Recall", ""])
    lines.append(
        f"- **Matched synthesized concepts**: {', '.join(m.matched_concepts_synthesized) or '*(none)*'}"
    )
    lines.append(
        f"- **Missed synthesized concepts**: {', '.join(m.missed_concepts_synthesized) or '*(none)*'}"
    )
    lines.append(f"- **Matched facts**: {', '.join(m.matched_facts) or '*(none)*'}")
    lines.append(f"- **Missed facts**: {', '.join(m.missed_facts) or '*(none)*'}")

    lines.extend(
        [
            "",
            "## Compiled Pages",
            "",
            "| Slug | Kind | Title | Links | Backlinks | Chars |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for p in report.pages:
        lines.append(
            f"| `{p.slug}` | `{p.page_kind}` | {p.title} | {len(p.outbound_links)} | {len(p.backlinks)} | {p.body_chars} |"
        )
    if not report.pages:
        lines.append("| *(none)* | — | — | 0 | 0 | 0 |")

    lines.extend(["", "## Batch Trace", ""])
    lines.append("| Batch | Events | Pages Updated | Open Lint | Elapsed (s) |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for b in report.batches:
        lines.append(
            f"| {b.batch_no} | {b.events_processed} | {b.pages_updated} | {b.lint_issues_open} | {b.elapsed_seconds:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)
