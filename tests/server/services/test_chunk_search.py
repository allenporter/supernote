"""Unit tests for modular keyword/embedding chunk searchers and hybrid ranking."""

from __future__ import annotations

import json
from datetime import date

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.chunk_search import (
    EmbeddingChunkSearcher,
    KeywordChunkSearcher,
    SearchQuery,
    SearchResult,
    normalize_keyword_query,
    rank_and_merge_results,
)


def _kw_json(*tags: str) -> str:
    return json.dumps([{"KEYWORDPAGE": "1", "KEYWORD": tag} for tag in tags])


async def _seed_single_page(
    session_manager: DatabaseSessionManager,
    *,
    keywords: tuple[str, ...] = (),
    text_content: str | None = None,
    page_id: str = "P20260401090000abc",
) -> None:
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=1,
                file_name="Lab.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        if keywords:
            session.add(
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id=page_id,
                    keywords_json=_kw_json(*keywords),
                )
            )
        if text_content is not None:
            session.add(
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id=page_id,
                    text_content=text_content,
                )
            )
        await session.commit()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#KS-Tilt", "ks-tilt"),
        ("  #roadmap   #Q4  ", "roadmap q4"),
        ("C#", "c#"),
        ("C++", "c++"),
        ("$100", "$100"),
        ("###", ""),
        ("---", ""),
        ("   ", ""),
    ],
)
def test_normalize_keyword_query(raw: str, expected: str) -> None:
    assert normalize_keyword_query(raw) == expected


@pytest.mark.parametrize(
    ("raw_query", "keywords", "expected_score", "expected_preview"),
    [
        (
            "#KS-Tilt",
            ("unrelated", "ks-tilt", "KS-TILT"),
            1.0,
            "Keywords: #ks-tilt, #unrelated",
        ),
        (
            "#roadmap #Q4",
            ("backlog", "roadmap", "Q4"),
            0.95,
            "Keywords: #roadmap, #Q4, #backlog",
        ),
        (
            "tilt",
            ("ks-tilt",),
            0.92,
            "Keywords: #ks-tilt",
        ),
        (
            "how to fix ks-tilt drift",
            ("ks-tilt",),
            0.88,
            "Keywords: #ks-tilt",
        ),
        (
            "trap",
            ("ks-trapezoid",),
            0.85,
            "Keywords: #ks-trapezoid",
        ),
        (
            "日本語 勉強",
            ("日本語の勉強",),
            0.85,
            "Keywords: #日本語の勉強",
        ),
    ],
)
async def test_keyword_searcher_native_tag_scoring_and_preview_ordering(
    session_manager: DatabaseSessionManager,
    raw_query: str,
    keywords: tuple[str, ...],
    expected_score: float,
    expected_preview: str,
) -> None:
    await _seed_single_page(session_manager, keywords=keywords)
    searcher = KeywordChunkSearcher(session_manager)

    hits = await searcher.search(SearchQuery(user_id=1, raw_query=raw_query))
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="Lab.note",
            page_index=0,
            page_id="P20260401090000abc",
            score=expected_score,
            text_preview=expected_preview,
            date="2026-04-01",
        )
    ]


@pytest.mark.parametrize(
    ("raw_query", "keywords", "text_content"),
    [
        ("cat", ("vacation",), None),
        ("notes on alignment", ("on",), None),
        ("notes", (), "This page is not ready yet."),
        ("C#", ("C++",), "Modern C++ reference."),
        ("C++", ("Vitamin C",), "Daily vitamin C log."),
        ("$100", (), "Counted 100 resistors in bin."),
        ("###", ("ks-tilt",), "ks-tilt calibration"),
        ("---", ("ks-tilt",), "ks-tilt calibration"),
    ],
)
async def test_keyword_searcher_rejects_false_positive_matches(
    session_manager: DatabaseSessionManager,
    raw_query: str,
    keywords: tuple[str, ...],
    text_content: str | None,
) -> None:
    await _seed_single_page(
        session_manager, keywords=keywords, text_content=text_content
    )
    searcher = KeywordChunkSearcher(session_manager)

    assert await searcher.search(SearchQuery(user_id=1, raw_query=raw_query)) == []


@pytest.mark.parametrize(
    ("raw_query", "keywords", "text_content", "expected_score"),
    [
        ("telescope alignment?", (), "Checked telescope alignment last night.", 0.85),
        ("v1.2 release", (), "Notes on the v1.2 release schedule.", 0.85),
        ("alignment mirror", (), "Primary mirror needs careful laser alignment.", 0.75),
        ("C++", (), "Modern C++ templates and concepts.", 0.85),
        ("日本語？", (), "毎日日本語を勉強する。", 0.85),
        ("日本語、勉強？", (), "毎日日本語を勉強する。", 0.75),
        ("optics", ("optics-lab",), "Optics bench collimation.", 0.92 + 0.05 * 0.85),
    ],
)
async def test_keyword_searcher_transcript_and_combined_boost(
    session_manager: DatabaseSessionManager,
    raw_query: str,
    keywords: tuple[str, ...],
    text_content: str,
    expected_score: float,
) -> None:
    await _seed_single_page(
        session_manager, keywords=keywords, text_content=text_content
    )
    searcher = KeywordChunkSearcher(session_manager)

    hits = await searcher.search(SearchQuery(user_id=1, raw_query=raw_query))
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(expected_score)
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="Lab.note",
            page_index=0,
            page_id="P20260401090000abc",
            score=hits[0].score,
            text_preview=text_content,
            date="2026-04-01",
        )
    ]


async def test_keyword_searcher_legacy_empty_page_id_slots_do_not_cross_join(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=1,
                file_name="Legacy.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        session.add_all(
            [
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="",
                    keywords_json=_kw_json("ks-tilt"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=1,
                    page_id="",
                    keywords_json=_kw_json("ks-tilt"),
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="",
                    text_content="Legacy page two ks-tilt notes.",
                ),
            ]
        )
        await session.commit()

    searcher = KeywordChunkSearcher(session_manager)
    hits = await searcher.search(SearchQuery(user_id=1, raw_query="#ks-tilt"))
    assert sorted(hits, key=lambda r: r.page_index) == [
        SearchResult(
            file_id=101,
            file_name="Legacy.note",
            page_index=0,
            page_id="",
            score=1.0,
            text_preview="Keywords: #ks-tilt",
            date=None,
        ),
        SearchResult(
            file_id=101,
            file_name="Legacy.note",
            page_index=1,
            page_id="",
            score=1.0,
            text_preview="Legacy page two ks-tilt notes.",
            date=None,
        ),
    ]


async def test_keyword_searcher_whitespace_ocr_preserves_keywords_preview(
    session_manager: DatabaseSessionManager,
) -> None:
    await _seed_single_page(
        session_manager, keywords=("ks-tilt",), text_content="   \n\t  "
    )
    searcher = KeywordChunkSearcher(session_manager)

    hits = await searcher.search(SearchQuery(user_id=1, raw_query="#ks-tilt"))
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="Lab.note",
            page_index=0,
            page_id="P20260401090000abc",
            score=1.0,
            text_preview="Keywords: #ks-tilt",
            date="2026-04-01",
        )
    ]


async def test_keyword_searcher_escapes_sql_wildcards_in_name_filter(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="100%_Notes.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                UserFileDO(
                    id=102,
                    user_id=1,
                    file_name="1000XNotes.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000abc",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=102,
                    page_index=0,
                    page_id="P20260401090000def",
                    keywords_json=_kw_json("optics"),
                ),
            ]
        )
        await session.commit()

    searcher = KeywordChunkSearcher(session_manager)
    hits = await searcher.search(
        SearchQuery(user_id=1, raw_query="#optics", name_filter="100%_")
    )
    assert [h.file_name for h in hits] == ["100%_Notes.note"]


async def test_keyword_searcher_filters_by_inferred_page_dates(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=1,
                file_name="Journal.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        session.add_all(
            [
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="P20260310080000abc",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=1,
                    page_id="P20260315235959def",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=2,
                    page_id="legacy_no_date",
                    keywords_json=_kw_json("optics"),
                ),
            ]
        )
        await session.commit()

    searcher = KeywordChunkSearcher(session_manager)
    hits = await searcher.search(
        SearchQuery(
            user_id=1,
            raw_query="#optics",
            after_date=date(2026, 3, 12),
            before_date=date(2026, 3, 15),
        )
    )
    assert [(h.page_index, h.date) for h in hits] == [(1, "2026-03-15")]


async def test_keyword_searcher_isolates_active_user_files(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="Active.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                UserFileDO(
                    id=102,
                    user_id=1,
                    file_name="Deleted.note",
                    directory_id=0,
                    is_active="N",
                    is_folder="N",
                ),
                UserFileDO(
                    id=103,
                    user_id=2,
                    file_name="OtherUser.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="p0",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=102,
                    page_index=0,
                    page_id="p0",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=2,
                    file_id=103,
                    page_index=0,
                    page_id="p0",
                    keywords_json=_kw_json("optics"),
                ),
            ]
        )
        await session.commit()

    searcher = KeywordChunkSearcher(session_manager)
    hits = await searcher.search(SearchQuery(user_id=1, raw_query="#optics"))
    assert [h.file_id for h in hits] == [101]


class _FailingEmbeddingModel(EmbeddingModel):
    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return "failing-v1"

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        raise AIError("embedding backend unavailable")


@pytest.mark.parametrize(
    ("model", "raw_query"),
    [
        (None, "optics"),
        (_FailingEmbeddingModel(), "optics"),
        (FakeEmbeddingModel(dimensions=3, model_id="fake-v1"), "   "),
    ],
)
async def test_embedding_searcher_guard_clauses_and_ai_error(
    session_manager: DatabaseSessionManager,
    model: EmbeddingModel | None,
    raw_query: str,
) -> None:
    searcher = EmbeddingChunkSearcher(session_manager, model)
    assert await searcher.search(SearchQuery(user_id=1, raw_query=raw_query)) == []


async def test_embedding_searcher_skips_malformed_mismatched_and_zero_norm_vectors(
    session_manager: DatabaseSessionManager,
) -> None:
    model = FakeEmbeddingModel(dimensions=3, model_id="fake-v1")
    query_vec = await model.embed("optics", task_type=EmbeddingTaskType.RETRIEVAL_QUERY)

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=1,
                file_name="Vectors.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        session.add_all(
            [
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="p0",
                    text_content="Malformed JSON",
                    embedding="{not-json",
                    embedding_model="fake-v1",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="p1",
                    text_content="Dimension mismatch",
                    embedding=json.dumps([1.0, 0.0]),
                    embedding_model="fake-v1",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=2,
                    page_id="p2",
                    text_content="Zero norm",
                    embedding=json.dumps([0.0, 0.0, 0.0]),
                    embedding_model="fake-v1",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=3,
                    page_id="P20260401090000abc",
                    text_content="Valid vector hit",
                    embedding=json.dumps(query_vec),
                    embedding_model="fake-v1",
                ),
            ]
        )
        await session.commit()

    hits = await EmbeddingChunkSearcher(session_manager, model).search(
        SearchQuery(user_id=1, raw_query="optics")
    )
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(1.0)
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="Vectors.note",
            page_index=3,
            page_id="P20260401090000abc",
            score=hits[0].score,
            text_preview="Valid vector hit",
            date="2026-04-01",
        )
    ]


def test_rank_and_merge_results_boosts_hybrid_and_breaks_ties() -> None:
    kw_hits = [
        SearchResult(1, "Neg.note", 0, "p_neg", 1.0, "Keywords: #optics"),
        SearchResult(2, "Unembedded.note", 0, "p_unemb", 1.0, "Keywords: #optics"),
        SearchResult(3, "Hybrid.note", 0, "p_pos", 1.0, "Keywords: #optics"),
    ]
    vec_hits = [
        SearchResult(1, "Neg.note", 0, "p_neg", -0.4, "Unrelated transcript"),
        SearchResult(3, "Hybrid.note", 0, "p_pos", 0.8, "Optics collimation notes"),
        SearchResult(4, "Orthogonal.note", 0, "p_orth", 0.0, "Other notes"),
    ]

    merged = rank_and_merge_results(kw_hits, vec_hits, top_n=10)
    assert merged == [
        SearchResult(3, "Hybrid.note", 0, "p_pos", 1.0, "Optics collimation notes"),
        SearchResult(2, "Unembedded.note", 0, "p_unemb", 1.0, "Keywords: #optics"),
        SearchResult(1, "Neg.note", 0, "p_neg", 1.0, "Unrelated transcript"),
        SearchResult(4, "Orthogonal.note", 0, "p_orth", 0.0, "Other notes"),
    ]


def test_rank_and_merge_results_reconciles_moved_page_by_page_id() -> None:
    kw_hits = [
        SearchResult(
            file_id=10,
            file_name="Moved.note",
            page_index=2,
            page_id="P20260401100000abc",
            score=0.92,
            text_preview="Keywords: #ks-tilt",
            date="2026-04-01",
        )
    ]
    vec_hits = [
        SearchResult(
            file_id=10,
            file_name="Moved.note",
            page_index=0,
            page_id="P20260401100000abc",
            score=0.6,
            text_preview="Detailed ks-tilt calibration steps.",
            date="2026-04-01",
        )
    ]

    merged = rank_and_merge_results(kw_hits, vec_hits, top_n=5)
    assert len(merged) == 1
    assert merged[0].score == pytest.approx(0.92 + 0.5 * 0.6 * 0.08)
    assert merged == [
        SearchResult(
            file_id=10,
            file_name="Moved.note",
            page_index=2,
            page_id="P20260401100000abc",
            score=merged[0].score,
            text_preview="Detailed ks-tilt calibration steps.",
            date="2026-04-01",
        )
    ]


def test_rank_and_merge_results_ignores_whitespace_vector_preview() -> None:
    kw_hits = [SearchResult(1, "A.note", 0, "p0", 1.0, "Keywords: #ks-tilt")]
    vec_hits = [SearchResult(1, "A.note", 0, "p0", 0.5, "   \n  ")]

    assert rank_and_merge_results(kw_hits, vec_hits, top_n=5) == [
        SearchResult(1, "A.note", 0, "p0", 1.0, "Keywords: #ks-tilt")
    ]


@pytest.mark.parametrize("top_n", [0, -1])
def test_rank_and_merge_results_non_positive_top_n(top_n: int) -> None:
    kw_hits = [SearchResult(1, "A.note", 0, "p0", 1.0, "Keywords: #ks-tilt")]
    assert rank_and_merge_results(kw_hits, [], top_n=top_n) == []
