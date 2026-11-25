"""Unit and integration tests for `evals.search` and `script/eval_search.py`."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from evals.search import (
    ALL_MODES,
    CachingEmbeddingModel,
    SearchEvalDataset,
    SearchEvalNotebook,
    SearchEvalPage,
    SearchEvalQuery,
    SearchEvalSuiteReport,
    evaluate_search_dataset,
    format_markdown_report,
    merge_suite_reports,
    rescore_suite_report,
    score_ranked_hits,
)
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "evals/search/dataset.yaml"
RESULTS_DIR = REPO_ROOT / "evals/search/results"
RESULTS_MD_PATH = REPO_ROOT / "evals/search/RESULTS.md"
SAVED_RESULT_FILES = (
    "gemini_embedding_001.json",
    "gemini_embedding_2.json",
    "openai_text_embedding_3_small.json",
    "ollama_embeddinggemma.json",
    "ollama_qwen3_embedding_0_6b.json",
    "ollama_qwen3_embedding_4b.json",
)


class _ControlledEmbeddingModel(EmbeddingModel):
    """Deterministic small-dim embedding model separating semantic vs noisy pages."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, EmbeddingTaskType]] = []

    @property
    def provider(self) -> str:
        return "test"

    @property
    def model_id(self) -> str:
        return "controlled-v1"

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        self.calls.append((text, task_type))
        lower = text.lower()
        if "rotator cuff" in lower or "shoulder pain" in lower:
            return [1.0, 0.0, 0.0, 0.0]
        if "tax" in lower or "irs" in lower:
            return [0.0, 1.0, 0.0, 0.0]
        if "scuba" in lower:
            # Low cosine (0.1) against all documents -> below 0.25 floor!
            return [0.1, 0.0, math.sqrt(1.0 - 0.01), 0.0]
        return [0.0, 0.0, 0.0, 1.0]


def test_score_ranked_hits_graded_and_unanswerable() -> None:
    """Verify graded nDCG/MRR/Recall/Precision and unanswerable abstention math."""
    # Relevant: p_best (grade 2 -> gain 3), p_ok (grade 1 -> gain 1)
    rel = {"p_best": 2, "p_ok": 1}

    # Returning [p_ok, p_best] puts grade-1 ahead of grade-2 -> nDCG < 1.0, Recall = 1.0, Precision = 1.0
    suboptimal = score_ranked_hits(["p_ok", "p_best"], rel, k=5)
    assert suboptimal.mrr == pytest.approx(1.0)
    assert suboptimal.recall == pytest.approx(1.0)
    assert suboptimal.precision == pytest.approx(1.0)
    expected_dcg = 1.0 / math.log2(2) + 3.0 / math.log2(3)
    expected_idcg = 3.0 / math.log2(2) + 1.0 / math.log2(3)
    assert suboptimal.ndcg == pytest.approx(expected_dcg / expected_idcg)
    assert suboptimal.abstained is None

    # Padding with 3 irrelevant items drops returned Precision@5 from 1.0 to 2/5 = 0.4
    padded = score_ranked_hits(["p_best", "p_ok", "junk1", "junk2", "junk3"], rel, k=5)
    assert padded.ndcg == pytest.approx(1.0)
    assert padded.precision == pytest.approx(0.4)

    # Empty result on answerable query -> 0 across all answerable metrics
    missed = score_ranked_hits([], rel, k=5)
    assert missed.ndcg == 0.0
    assert missed.mrr == 0.0
    assert missed.recall == 0.0
    assert missed.precision == 0.0

    # Unanswerable query -> abstained = 1.0 when empty, 0.0 when non-empty
    assert score_ranked_hits([], {}, k=5).abstained == 1.0
    assert score_ranked_hits(["junk1"], {}, k=5).abstained == 0.0


def test_dataset_validation_invariants() -> None:
    """Verify dataset validation catches invalid filenames, unknown pages, and bad grades."""
    with pytest.raises(ValueError, match=r"end with \.note"):
        SearchEvalDataset(
            notebooks=[SearchEvalNotebook(file_name="bad.txt", pages=[])],
            queries=[],
        )

    nb = SearchEvalNotebook(
        file_name="Notes.note",
        pages=[SearchEvalPage(id="p0", page_index=0, text_content="hello")],
    )
    with pytest.raises(ValueError, match="unknown page id"):
        SearchEvalDataset(
            notebooks=[nb],
            queries=[
                SearchEvalQuery(
                    id="q1",
                    category="exact_lexical",
                    query="hello",
                    relevant_pages={"missing": 2},
                )
            ],
        )

    with pytest.raises(ValueError, match="empty relevant_pages"):
        SearchEvalDataset(
            notebooks=[nb],
            queries=[
                SearchEvalQuery(
                    id="q_neg",
                    category="unanswerable_negative",
                    query="nope",
                    relevant_pages={"p0": 1},
                )
            ],
        )


async def test_caching_embedding_model_and_all_five_modes(tmp_path: Path) -> None:
    """Verify disk vector caching, all 5 retrieval modes, rescoring, and markdown rendering."""
    dataset = SearchEvalDataset(
        name="mini-suite",
        notebooks=[
            SearchEvalNotebook(
                file_name="Health.note",
                pages=[
                    SearchEvalPage(
                        id="p_shoulder",
                        page_index=0,
                        page_id="P20260510090000abcdefghijkl",
                        keywords=["rehab"],
                        text_content="Rotator cuff external rotation 3x15.",
                    ),
                    SearchEvalPage(
                        id="p_tax",
                        page_index=1,
                        page_id="P20260115090000abcdefghijkl",
                        keywords=["irs-2025"],
                        text_content="Quarterly voucher mailed.",
                    ),
                ],
            )
        ],
        queries=[
            SearchEvalQuery(
                id="q_tag",
                category="tag_lookup",
                query="#rehab",
                relevant_pages={"p_shoulder": 2},
            ),
            SearchEvalQuery(
                id="q_sem",
                category="semantic_paraphrase",
                query="shoulder pain exercises",
                relevant_pages={"p_shoulder": 2},
            ),
            SearchEvalQuery(
                id="q_neg",
                category="unanswerable_negative",
                query="scuba diving regulator",
                relevant_pages={},
            ),
        ],
    )

    inner = _ControlledEmbeddingModel()
    cache_file = tmp_path / "cache.json"
    cached_model = CachingEmbeddingModel(inner, cache_path=cache_file)

    report = await evaluate_search_dataset(
        dataset,
        cached_model,
        modes=ALL_MODES,
        cutoffs=(5, 10),
        seed=7,
    )
    assert cache_file.exists()
    # 2 documents + 3 queries = 5 unique calls despite running 3 vector modes x 2 cutoffs!
    assert cached_model.api_calls == 5
    assert cached_model.cache_hits > 0

    by_mode = {m.mode: m for m in report.modes}
    # Hybrid nails both #rehab (tag) and "shoulder pain exercises" (semantic) AND abstains on scuba!
    assert by_mode["hybrid"].overall_by_k[5].mean_ndcg == pytest.approx(1.0)
    assert by_mode["hybrid"].overall_by_k[5].abstention_rate == pytest.approx(1.0)
    # Unfloored embedding returns low-cosine docs on unanswerable query -> 0% abstention
    assert by_mode["embedding_unfloored"].overall_by_k[
        5
    ].abstention_rate == pytest.approx(0.0)
    assert by_mode["embedding_floored"].overall_by_k[
        5
    ].abstention_rate == pytest.approx(1.0)

    # Reload from JSON, merge with another target run, and rescore offline
    restored = SearchEvalSuiteReport.from_json(report.to_json())
    rescored = rescore_suite_report(restored, dataset)
    alt_report = await evaluate_search_dataset(
        dataset,
        FakeEmbeddingModel(dimensions=4, model_id="blended", blended=True),
        modes=ALL_MODES,
        cutoffs=(5, 10),
        seed=7,
    )
    merged = merge_suite_reports([rescored, alt_report])
    # random:none and keyword_only:none deduplicated -> 2 + 3 + 3 = 8 rows
    assert len(merged.modes) == 8
    md = format_markdown_report(merged)
    assert "## Overall Summary (`top_n=5`)" in md
    assert "## Overall Summary (`top_n=10`)" in md
    assert "`hybrid`" in md


async def test_checked_in_search_dataset_loads_and_runs_smoke() -> None:
    """Ensure the checked-in `evals/search/dataset.yaml` is valid and runnable."""
    if not DATASET_PATH.exists():
        pytest.skip("dataset.yaml not yet assembled")
    dataset = SearchEvalDataset.load(DATASET_PATH)
    assert len(dataset.notebooks) >= 10
    assert sum(len(nb.pages) for nb in dataset.notebooks) >= 80
    assert len(dataset.queries) >= 50

    # Smoke-test 3 queries across all 5 modes with FakeEmbeddingModel(blended=True)
    subset = SearchEvalDataset(
        name=dataset.name,
        notebooks=dataset.notebooks,
        queries=dataset.queries[:3],
    )
    report = await evaluate_search_dataset(
        subset,
        FakeEmbeddingModel(model_id="blended", blended=True),
        cutoffs=(5,),
    )
    assert len(report.modes) == 5


def test_checked_in_results_md_matches_saved_json_reports() -> None:
    """Ensure checked-in `evals/search/RESULTS.md` stays synced with saved JSON runs."""
    dataset = SearchEvalDataset.load(DATASET_PATH)
    reports = [
        rescore_suite_report(
            SearchEvalSuiteReport.from_json(
                (RESULTS_DIR / name).read_text(encoding="utf-8")
            ),
            dataset,
        )
        for name in SAVED_RESULT_FILES
    ]
    merged = merge_suite_reports(reports)
    expected_md = format_markdown_report(merged)
    assert RESULTS_MD_PATH.read_text(encoding="utf-8") == expected_md
