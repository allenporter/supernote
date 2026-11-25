"""Declarative retrieval evaluation harness for comparing search modes.

Benchmarks five retrieval modes (`random`, `keyword_only`, `embedding_unfloored`,
`embedding_floored`, and `hybrid`) against a ground-truth YAML corpus of Supernote
notebooks, native page keywords, and OCR transcripts across `top_n` cutoffs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
import statistics
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.yaml import DataClassYAMLMixin
from sqlalchemy import Select, select

from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.components.search.chunk_search import (
    EmbeddingChunkSearcher,
    SearchQuery,
)
from supernote.server.components.search.service import SearchService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.note_content import infer_page_date

RetrievalMode = Literal[
    "random",
    "keyword_only",
    "embedding_unfloored",
    "embedding_floored",
    "hybrid",
]

ALL_MODES: tuple[RetrievalMode, ...] = (
    "random",
    "keyword_only",
    "embedding_unfloored",
    "embedding_floored",
    "hybrid",
)
DEFAULT_CUTOFFS: tuple[int, ...] = (5, 10)
UNANSWERABLE_CATEGORY = "unanswerable_negative"
_EVAL_USER_ID = 1
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class SearchEvalPage(DataClassYAMLMixin, DataClassJSONMixin):
    """Single indexed notebook page in a search evaluation dataset."""

    id: str
    page_index: int
    page_id: str = ""
    keywords: list[str] = field(default_factory=list)
    text_content: str = ""


@dataclass
class SearchEvalNotebook(DataClassYAMLMixin, DataClassJSONMixin):
    """Notebook container grouping ordered pages in a search evaluation dataset."""

    file_name: str
    description: str = ""
    pages: list[SearchEvalPage] = field(default_factory=list)


@dataclass
class SearchEvalQuery(DataClassYAMLMixin, DataClassJSONMixin):
    """Evaluation query with optional scope filters and graded ground-truth labels."""

    id: str
    category: str
    query: str
    name_filter: str | None = None
    date_after: str | None = None
    date_before: str | None = None
    description: str = ""
    relevant_pages: dict[str, int] = field(default_factory=dict)

    @property
    def is_unanswerable(self) -> bool:
        """Return True when no page in the corpus is relevant to this query."""
        return len(self.relevant_pages) == 0


@dataclass
class SearchEvalDataset(DataClassYAMLMixin, DataClassJSONMixin):
    """Declarative search evaluation dataset loaded from YAML."""

    name: str = "supernote-search-suite-v1"
    notebooks: list[SearchEvalNotebook] = field(default_factory=list)
    queries: list[SearchEvalQuery] = field(default_factory=list)

    def __post_init__(self) -> None:
        seen_files: set[str] = set()
        seen_pages: set[str] = set()
        for nb in self.notebooks:
            if not nb.file_name.lower().endswith(".note"):
                raise ValueError(
                    f"Notebook file_name must end with .note: {nb.file_name!r}"
                )
            if nb.file_name in seen_files:
                raise ValueError(f"Duplicate notebook file_name: {nb.file_name!r}")
            seen_files.add(nb.file_name)
            for expected_idx, page in enumerate(nb.pages):
                if page.page_index != expected_idx:
                    raise ValueError(
                        f"Page {page.id!r} in {nb.file_name!r} expected page_index "
                        f"{expected_idx}, got {page.page_index}"
                    )
                if not page.id or page.id in seen_pages:
                    raise ValueError(f"Invalid or duplicate page id: {page.id!r}")
                seen_pages.add(page.id)

        seen_queries: set[str] = set()
        for q in self.queries:
            if not q.id or q.id in seen_queries:
                raise ValueError(f"Invalid or duplicate query id: {q.id!r}")
            seen_queries.add(q.id)
            if not q.query or not q.query.strip():
                raise ValueError(f"Query {q.id!r} must have non-empty query text.")
            if q.category == UNANSWERABLE_CATEGORY and q.relevant_pages:
                raise ValueError(
                    f"Unanswerable query {q.id!r} must have empty relevant_pages."
                )
            if q.category != UNANSWERABLE_CATEGORY and not q.relevant_pages:
                raise ValueError(
                    f"Answerable query {q.id!r} ({q.category}) must list >= 1 relevant page."
                )
            for pid, grade in q.relevant_pages.items():
                if pid not in seen_pages:
                    raise ValueError(
                        f"Query {q.id!r} references unknown page id {pid!r}."
                    )
                if grade not in (1, 2):
                    raise ValueError(
                        f"Query {q.id!r} page {pid!r} grade must be 1 or 2, got {grade}."
                    )

    @classmethod
    def load(cls, manifest_path: Path) -> SearchEvalDataset:
        """Load and validate a `SearchEvalDataset` from a YAML manifest."""
        return cls.from_yaml(manifest_path.read_text(encoding="utf-8"))


class CachingEmbeddingModel(EmbeddingModel):
    """Disk-backed content-addressed cache around an `EmbeddingModel`."""

    def __init__(
        self,
        inner: EmbeddingModel,
        cache_path: Path | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._inner = inner
        self._cache_path = cache_path
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._cache: dict[str, list[float]] = {}
        self.cache_hits = 0
        self.api_calls = 0
        if cache_path is not None and cache_path.exists():
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._cache = {str(k): list(v) for k, v in loaded.items()}

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @staticmethod
    def default_cache_path(cache_dir: Path, model: EmbeddingModel) -> Path:
        slug = _SAFE_FILENAME_RE.sub("_", f"{model.provider}_{model.model_id}")
        return cache_dir / f"{slug}.json"

    def flush(self) -> None:
        """Persist cached vectors to `cache_path` if configured."""
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._cache, sort_keys=True), encoding="utf-8"
        )

    async def embed(
        self,
        text: str,
        task_type: EmbeddingTaskType,
    ) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = f"{self.provider}:{self.model_id}:{task_type.value}:{digest}"
        if (cached := self._cache.get(key)) is not None:
            self.cache_hits += 1
            return cached
        async with self._sem:
            if (cached := self._cache.get(key)) is not None:
                self.cache_hits += 1
                return cached
            vec = await self._inner.embed(text, task_type=task_type)
            self._cache[key] = vec
            self.api_calls += 1
            return vec


@dataclass
class CutoffMetrics(DataClassJSONMixin):
    """Per-query IR scores at a single rank cutoff `k`."""

    k: int
    ndcg: float | None = None
    mrr: float | None = None
    recall: float | None = None
    precision: float | None = None
    abstained: float | None = None


@dataclass
class QueryModeResult(DataClassJSONMixin):
    """Per-query ranked output and metrics for a single retrieval mode."""

    query_id: str
    category: str
    hits_by_k: dict[int, list[str]]
    latency_ms: float
    by_k: dict[int, CutoffMetrics]


@dataclass
class SliceSummary(DataClassJSONMixin):
    """Aggregated IR metrics across all queries (or one query category) at cutoff `k`."""

    category: str
    k: int
    query_count: int
    answerable_count: int
    unanswerable_count: int
    mean_ndcg: float | None
    mean_mrr: float | None
    mean_recall: float | None
    mean_precision: float | None
    abstention_rate: float | None
    median_latency_ms: float


@dataclass
class ModeReport(DataClassJSONMixin):
    """Evaluation summary and per-query trace for one retrieval mode."""

    mode: str
    embedding_target: str
    overall_by_k: dict[int, SliceSummary]
    by_category: list[SliceSummary]
    queries: list[QueryModeResult]


@dataclass
class SearchEvalSuiteReport(DataClassJSONMixin):
    """Full multi-mode search benchmark report across a `SearchEvalDataset`."""

    dataset_name: str
    notebook_count: int
    page_count: int
    query_count: int
    embedding_target: str
    cutoffs: list[int]
    modes: list[ModeReport]


def score_ranked_hits(
    ranked_page_ids: Sequence[str],
    relevant_pages: Mapping[str, int],
    k: int,
) -> CutoffMetrics:
    """Compute graded IR metrics (`nDCG@k`, `MRR@k`, `Recall@k`, `Precision@k`, `Abstained`).

    On answerable queries (`relevant_pages` non-empty):
    - `ndcg`: Exponential gain `(2**grade - 1) / log2(rank + 1)` normalized by ideal DCG@k.
    - `mrr`: Reciprocal rank `1 / rank` of the highest-ranked relevant page (`grade >= 1`).
    - `recall`: Fraction of all relevant pages (`grade >= 1`) appearing in `ranked_page_ids[:k]`.
    - `precision`: Fraction of returned cards `ranked_page_ids[:k]` that are relevant
      (`0.0` if empty), penalizing noise padding when fewer than `k` pages are relevant.

    On unanswerable queries (`relevant_pages` empty):
    - `abstained`: `1.0` when `ranked_page_ids[:k]` is empty, else `0.0`.
    """
    top_hits = list(dict.fromkeys(ranked_page_ids[:k]))
    if not relevant_pages:
        return CutoffMetrics(k=k, abstained=1.0 if len(top_hits) == 0 else 0.0)

    dcg = 0.0
    mrr = 0.0
    rel_found = 0
    for idx, pid in enumerate(top_hits):
        grade = relevant_pages.get(pid, 0)
        if grade > 0:
            rel_found += 1
            if mrr == 0.0:
                mrr = 1.0 / (idx + 1)
            dcg += float((1 << grade) - 1) / math.log2(idx + 2)

    ideal_grades = sorted(relevant_pages.values(), reverse=True)[:k]
    idcg = sum(
        float((1 << g) - 1) / math.log2(idx + 2) for idx, g in enumerate(ideal_grades)
    )
    return CutoffMetrics(
        k=k,
        ndcg=(dcg / idcg) if idcg > 0.0 else 0.0,
        mrr=mrr,
        recall=rel_found / len(relevant_pages),
        precision=(rel_found / len(top_hits)) if top_hits else 0.0,
    )


def _summarize_slice(
    category: str,
    k: int,
    results: Sequence[QueryModeResult],
) -> SliceSummary:
    ndcgs = [m.ndcg for r in results if (m := r.by_k[k]).ndcg is not None]
    mrrs = [m.mrr for r in results if (m := r.by_k[k]).mrr is not None]
    recalls = [m.recall for r in results if (m := r.by_k[k]).recall is not None]
    precisions = [
        m.precision for r in results if (m := r.by_k[k]).precision is not None
    ]
    abstains = [m.abstained for r in results if (m := r.by_k[k]).abstained is not None]
    latencies = [r.latency_ms for r in results]
    return SliceSummary(
        category=category,
        k=k,
        query_count=len(results),
        answerable_count=len(ndcgs),
        unanswerable_count=len(abstains),
        mean_ndcg=statistics.fmean(ndcgs) if ndcgs else None,
        mean_mrr=statistics.fmean(mrrs) if mrrs else None,
        mean_recall=statistics.fmean(recalls) if recalls else None,
        mean_precision=statistics.fmean(precisions) if precisions else None,
        abstention_rate=statistics.fmean(abstains) if abstains else None,
        median_latency_ms=statistics.median(latencies) if latencies else 0.0,
    )


def _build_mode_report(
    mode: str,
    embedding_target: str,
    query_results: list[QueryModeResult],
    cutoffs: Sequence[int],
) -> ModeReport:
    overall_by_k = {k: _summarize_slice("overall", k, query_results) for k in cutoffs}
    categories = list(dict.fromkeys(r.category for r in query_results))
    by_category = [
        _summarize_slice(cat, k, [r for r in query_results if r.category == cat])
        for k in cutoffs
        for cat in categories
    ]
    return ModeReport(
        mode=mode,
        embedding_target=embedding_target,
        overall_by_k=overall_by_k,
        by_category=by_category,
        queries=query_results,
    )


async def _seed_eval_database(
    session_manager: DatabaseSessionManager,
    dataset: SearchEvalDataset,
    embedding_model: EmbeddingModel | None,
) -> dict[tuple[int, int], str]:
    """Populate an isolated SQLite DB with dataset notebooks, keywords, texts, and embeddings."""
    await session_manager.create_all_tables()
    slug_by_file_page: dict[tuple[int, int], str] = {}

    embedded_by_slug: dict[str, str] = {}
    if embedding_model is not None:
        non_blank_pages = [
            page
            for nb in dataset.notebooks
            for page in nb.pages
            if page.text_content and page.text_content.strip()
        ]
        vectors = await asyncio.gather(
            *(
                embedding_model.embed(
                    page.text_content, task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
                )
                for page in non_blank_pages
            )
        )
        for page, vec in zip(non_blank_pages, vectors, strict=True):
            embedded_by_slug[page.id] = json.dumps(vec)

    async with session_manager.session() as session:
        session.add(
            UserDO(
                id=_EVAL_USER_ID,
                display_name="Eval User",
                email="eval@example.com",
                password_md5="0" * 32,
            )
        )
        await session.flush()

        content_id = 1000
        for nb_idx, nb in enumerate(dataset.notebooks, start=100):
            seen_content_pids: set[str] = set()
            session.add(
                UserFileDO(
                    id=nb_idx,
                    user_id=_EVAL_USER_ID,
                    directory_id=0,
                    file_name=nb.file_name,
                    is_folder="N",
                    is_active="Y",
                )
            )
            for page in nb.pages:
                slug_by_file_page[(nb_idx, page.page_index)] = page.id
                kw_json = json.dumps(
                    [
                        {"KEYWORDPAGE": str(page.page_index + 1), "KEYWORD": kw}
                        for kw in page.keywords
                    ]
                )
                session.add(
                    NotePageMetadataDO(
                        user_id=_EVAL_USER_ID,
                        file_id=nb_idx,
                        page_index=page.page_index,
                        page_id=page.page_id,
                        has_ink=bool(page.text_content.strip()),
                        keywords_json=kw_json,
                    )
                )
                # Mirror PageHashingModule: legacy files lacking `<PAGEID>` (`page_id == ""`)
                # only persist `NotePageMetadataDO` rows when multiple pages lack IDs.
                if not page.page_id or page.page_id in seen_content_pids:
                    continue
                seen_content_pids.add(page.page_id)
                emb_json = embedded_by_slug.get(page.id)
                content_id += 1
                session.add(
                    NotePageContentDO(
                        id=content_id,
                        file_id=nb_idx,
                        page_index=page.page_index,
                        page_id=page.page_id,
                        text_content=page.text_content,
                        embedding=emb_json,
                        embedding_model=(
                            embedding_model.model_id
                            if emb_json is not None and embedding_model
                            else None
                        ),
                    )
                )
        await session.commit()

    return slug_by_file_page


def _parse_query_dates(q: SearchEvalQuery) -> tuple[date | None, date | None]:
    after = date.fromisoformat(q.date_after) if q.date_after else None
    before = date.fromisoformat(q.date_before) if q.date_before else None
    return after, before


def _matches_date_window(
    page_id: str,
    after_date: date | None,
    before_date: date | None,
) -> bool:
    inferred = infer_page_date(page_id)
    day = inferred.date() if inferred is not None else None
    if after_date and (day is None or day < after_date):
        return False
    if before_date and (day is None or day > before_date):
        return False
    return True


def _apply_eval_file_filters[*Ts](
    stmt: Select[*Ts], name_filter: str | None
) -> Select[*Ts]:
    stmt = (
        stmt.where(UserFileDO.user_id == _EVAL_USER_ID)
        .where(UserFileDO.is_active == "Y")
        .where(UserFileDO.is_folder == "N")
        .where(UserFileDO.file_name.ilike("%.note"))
    )
    if name_filter:
        stmt = stmt.where(UserFileDO.file_name.icontains(name_filter, autoescape=True))
    return stmt


async def _run_single_mode_cutoff(
    mode: RetrievalMode,
    q: SearchEvalQuery,
    top_n: int,
    *,
    session_manager: DatabaseSessionManager,
    hybrid_service: SearchService,
    lexical_service: SearchService,
    vector_searcher: EmbeddingChunkSearcher,
    embedding_model: EmbeddingModel | None,
    slug_by_file_page: Mapping[tuple[int, int], str],
    seed: int,
) -> list[str]:
    if mode in ("hybrid", "keyword_only"):
        svc = hybrid_service if mode == "hybrid" else lexical_service
        hits = await svc.search_chunks(
            user_id=_EVAL_USER_ID,
            query=q.query,
            top_n=top_n,
            name_filter=q.name_filter,
            date_after=q.date_after,
            date_before=q.date_before,
        )
        return [slug_by_file_page[(r.file_id, r.page_index)] for r in hits]

    after_date, before_date = _parse_query_dates(q)
    if after_date and before_date and after_date > before_date:
        return []

    if mode == "embedding_floored":
        if embedding_model is None:
            raise ValueError(f"Mode {mode!r} requires an EmbeddingModel.")
        query_unit = await vector_searcher.embed_query(q.query, embedding_model)
        if query_unit is None:
            return []
        sq = SearchQuery(
            user_id=_EVAL_USER_ID,
            raw_query=q.query,
            top_n=top_n,
            name_filter=q.name_filter,
            after_date=after_date,
            before_date=before_date,
        )
        async with session_manager.session() as session:
            vec_hits = await vector_searcher.search(
                session, sq, query_unit, embedding_model
            )
        return [slug_by_file_page[(r.file_id, r.page_index)] for r in vec_hits[:top_n]]

    if mode == "embedding_unfloored":
        if embedding_model is None:
            raise ValueError(f"Mode {mode!r} requires an EmbeddingModel.")
        query_unit = await vector_searcher.embed_query(q.query, embedding_model)
        if query_unit is None:
            return []
        async with session_manager.session() as session:
            stmt = _apply_eval_file_filters(
                select(
                    NotePageContentDO.file_id,
                    NotePageContentDO.page_index,
                    NotePageContentDO.page_id,
                    NotePageContentDO.embedding,
                )
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(NotePageContentDO.embedding.isnot(None))
                .where(NotePageContentDO.embedding_model == embedding_model.model_id),
                q.name_filter,
            )
            emb_rows = (await session.execute(stmt)).all()

        scored_unfloored: list[tuple[float, int, int]] = []
        for row in emb_rows:
            if not row.embedding or not _matches_date_window(
                row.page_id, after_date, before_date
            ):
                continue
            cand = np.asarray(json.loads(row.embedding), dtype=float)
            norm = float(np.linalg.norm(cand))
            if not math.isfinite(norm) or math.isclose(norm, 0.0, abs_tol=1e-12):
                continue
            cos = max(-1.0, min(1.0, float(np.dot(query_unit, cand / norm))))
            scored_unfloored.append((cos, row.file_id, row.page_index))

        scored_unfloored.sort(key=lambda item: (-round(item[0], 6), item[1], item[2]))
        return [
            slug_by_file_page[(fid, pidx)] for _, fid, pidx in scored_unfloored[:top_n]
        ]

    if mode == "random":
        async with session_manager.session() as session:
            stmt = _apply_eval_file_filters(
                select(
                    NotePageMetadataDO.file_id,
                    NotePageMetadataDO.page_index,
                    NotePageMetadataDO.page_id,
                ).join(UserFileDO, UserFileDO.id == NotePageMetadataDO.file_id),
                q.name_filter,
            )
            rows = (await session.execute(stmt)).all()

        candidates = sorted(
            slug_by_file_page[(row.file_id, row.page_index)]
            for row in rows
            if _matches_date_window(row.page_id, after_date, before_date)
        )
        random.Random(f"{seed}:{q.id}:{top_n}").shuffle(candidates)
        return candidates[:top_n]

    raise ValueError(f"Unsupported retrieval mode: {mode!r}")


async def evaluate_search_dataset(
    dataset: SearchEvalDataset,
    embedding_model: EmbeddingModel | None,
    *,
    modes: Sequence[RetrievalMode] = ALL_MODES,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    seed: int = 42,
) -> SearchEvalSuiteReport:
    """Seed an ephemeral SQLite DB and benchmark all requested `modes` across `cutoffs`."""
    sorted_cutoffs = sorted(set(cutoffs))
    if not sorted_cutoffs or any(k <= 0 for k in sorted_cutoffs):
        raise ValueError(f"Cutoffs must be positive integers, got {cutoffs!r}")

    target_label = (
        f"{embedding_model.provider}:{embedding_model.model_id}"
        if embedding_model is not None
        else "none"
    )

    with tempfile.TemporaryDirectory(prefix="supernote_search_eval_") as tmpdir:
        db_url = f"sqlite+aiosqlite:///{Path(tmpdir) / 'eval.sqlite'}"
        session_manager = DatabaseSessionManager(db_url)
        try:
            slug_by_file_page = await _seed_eval_database(
                session_manager, dataset, embedding_model
            )
            hybrid_service = SearchService(session_manager, embedding_model)
            lexical_service = SearchService(session_manager, None)
            vector_searcher = EmbeddingChunkSearcher()

            mode_reports: list[ModeReport] = []
            for mode in modes:
                mode_target = (
                    "none" if mode in ("random", "keyword_only") else target_label
                )
                query_results: list[QueryModeResult] = []
                for q in dataset.queries:
                    hits_by_k: dict[int, list[str]] = {}
                    by_k: dict[int, CutoffMetrics] = {}
                    t0 = time.perf_counter()
                    for k in sorted_cutoffs:
                        hits = await _run_single_mode_cutoff(
                            mode,
                            q,
                            k,
                            session_manager=session_manager,
                            hybrid_service=hybrid_service,
                            lexical_service=lexical_service,
                            vector_searcher=vector_searcher,
                            embedding_model=embedding_model,
                            slug_by_file_page=slug_by_file_page,
                            seed=seed,
                        )
                        hits_by_k[k] = hits
                        by_k[k] = score_ranked_hits(hits, q.relevant_pages, k)
                    elapsed_ms = (
                        (time.perf_counter() - t0) * 1000.0 / len(sorted_cutoffs)
                    )
                    query_results.append(
                        QueryModeResult(
                            query_id=q.id,
                            category=q.category,
                            hits_by_k=hits_by_k,
                            latency_ms=elapsed_ms,
                            by_k=by_k,
                        )
                    )
                mode_reports.append(
                    _build_mode_report(mode, mode_target, query_results, sorted_cutoffs)
                )
        finally:
            await session_manager.close()

    if isinstance(embedding_model, CachingEmbeddingModel):
        embedding_model.flush()

    return SearchEvalSuiteReport(
        dataset_name=dataset.name,
        notebook_count=len(dataset.notebooks),
        page_count=sum(len(nb.pages) for nb in dataset.notebooks),
        query_count=len(dataset.queries),
        embedding_target=target_label,
        cutoffs=sorted_cutoffs,
        modes=mode_reports,
    )


def rescore_suite_report(
    report: SearchEvalSuiteReport,
    dataset: SearchEvalDataset,
) -> SearchEvalSuiteReport:
    """Recompute IR metrics on a saved `SearchEvalSuiteReport` against updated ground truth."""
    queries_by_id = {q.id: q for q in dataset.queries}
    updated_modes: list[ModeReport] = []
    for mode_rep in report.modes:
        rescored_queries: list[QueryModeResult] = []
        for qr in mode_rep.queries:
            q = queries_by_id.get(qr.query_id)
            if q is None:
                continue
            by_k = {
                int(k): score_ranked_hits(hits, q.relevant_pages, int(k))
                for k, hits in qr.hits_by_k.items()
            }
            rescored_queries.append(
                QueryModeResult(
                    query_id=qr.query_id,
                    category=q.category,
                    hits_by_k={int(k): v for k, v in qr.hits_by_k.items()},
                    latency_ms=qr.latency_ms,
                    by_k=by_k,
                )
            )
        updated_modes.append(
            _build_mode_report(
                mode_rep.mode,
                mode_rep.embedding_target,
                rescored_queries,
                report.cutoffs,
            )
        )
    return SearchEvalSuiteReport(
        dataset_name=dataset.name,
        notebook_count=len(dataset.notebooks),
        page_count=sum(len(nb.pages) for nb in dataset.notebooks),
        query_count=len(dataset.queries),
        embedding_target=report.embedding_target,
        cutoffs=report.cutoffs,
        modes=updated_modes,
    )


def merge_suite_reports(
    reports: Sequence[SearchEvalSuiteReport],
) -> SearchEvalSuiteReport:
    """Merge one or more saved suite reports, deduplicating `(mode, embedding_target)`."""
    if not reports:
        raise ValueError("merge_suite_reports requires at least one report.")
    if len(reports) == 1:
        return reports[0]

    first = reports[0]
    merged_by_key: dict[tuple[str, str], ModeReport] = {}
    targets: list[str] = []
    for rep in reports:
        if rep.dataset_name != first.dataset_name or rep.cutoffs != first.cutoffs:
            raise ValueError(
                "Cannot merge reports with mismatched dataset_name or cutoffs."
            )
        if rep.embedding_target not in targets and rep.embedding_target != "none":
            targets.append(rep.embedding_target)
        for m in rep.modes:
            merged_by_key[(m.mode, m.embedding_target)] = m

    return SearchEvalSuiteReport(
        dataset_name=first.dataset_name,
        notebook_count=first.notebook_count,
        page_count=first.page_count,
        query_count=first.query_count,
        embedding_target=", ".join(targets) if targets else first.embedding_target,
        cutoffs=list(first.cutoffs),
        modes=list(merged_by_key.values()),
    )


def _fmt_pct(val: float | None) -> str:
    return f"{val * 100.0:.1f}%" if val is not None else "—"


def format_markdown_report(report: SearchEvalSuiteReport) -> str:
    """Render a GitHub-flavored Markdown comparison table across modes and query categories."""
    lines = [
        f"# Search Retrieval Evaluation Report: `{report.dataset_name}`",
        "",
        f"- **Corpus**: `{report.page_count}` pages across `{report.notebook_count}` notebooks",
        f"- **Queries**: `{report.query_count}` ground-truth queries",
        f"- **Embedding Model**: `{report.embedding_target}`",
        "",
    ]

    for k in report.cutoffs:
        lines.extend(
            [
                f"## Overall Summary (`top_n={k}`)",
                "",
                "| Mode | Embedding | Answerable | Unanswerable | nDCG@"
                f"{k} | MRR@{k} | Recall@{k} | Precision@{k} | Abstention Rate | Median Latency |",
                "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for m in report.modes:
            s = m.overall_by_k[k]
            lines.append(
                f"| `{m.mode}` | `{m.embedding_target}` | {s.answerable_count} | "
                f"{s.unanswerable_count} | {_fmt_pct(s.mean_ndcg)} | "
                f"{_fmt_pct(s.mean_mrr)} | {_fmt_pct(s.mean_recall)} | "
                f"{_fmt_pct(s.mean_precision)} | {_fmt_pct(s.abstention_rate)} | "
                f"{s.median_latency_ms:.1f} ms |"
            )
        lines.append("")

    for k in report.cutoffs:
        lines.extend(
            [
                f"## Breakdown by Query Category (`top_n={k}`)",
                "",
                f"| Mode | Embedding | Category | Queries | nDCG@{k} | MRR@{k} | Recall@{k} | Precision@{k} | Abstention Rate |",
                "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for m in report.modes:
            for s in m.by_category:
                if s.k != k:
                    continue
                lines.append(
                    f"| `{m.mode}` | `{m.embedding_target}` | `{s.category}` | {s.query_count} | "
                    f"{_fmt_pct(s.mean_ndcg)} | {_fmt_pct(s.mean_mrr)} | "
                    f"{_fmt_pct(s.mean_recall)} | {_fmt_pct(s.mean_precision)} | "
                    f"{_fmt_pct(s.abstention_rate)} |"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
