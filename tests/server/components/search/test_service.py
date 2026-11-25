"""Unit tests for `supernote.server.components.search.service.SearchService`."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.processor.page_hashing import PageHashingModule
from supernote.server.components.search import (
    NotebookInfo,
    SearchResult,
    SearchService,
)
from supernote.server.components.search.lexical_scoring import extract_centered_snippet
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.testing.notebook_fixtures import build_synthetic_notebook

_TAIL_TRANSCRIPT = (
    "General standup status items. " * 8
    + "Calibrated parabolic mirror focal ratio at midnight."
)


def _kw_json(*tags: str) -> str:
    return json.dumps([{"KEYWORDPAGE": "1", "KEYWORD": tag} for tag in tags])


class _FailingEmbeddingModel(EmbeddingModel):
    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return "failing-v1"

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        raise AIError("embedding backend unavailable")


@pytest.fixture
def search_service(
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> SearchService:
    return SearchService(
        session_manager=session_manager,
        embedding_model=fake_embedding_model,
    )


@pytest.fixture
async def lexical_only_service(
    session_manager: DatabaseSessionManager,
) -> SearchService:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="100%_Active.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                UserFileDO(
                    id=102,
                    user_id=1,
                    file_name="100%_Deleted.note",
                    directory_id=0,
                    is_active="N",
                    is_folder="N",
                ),
                UserFileDO(
                    id=103,
                    user_id=2,
                    file_name="100%_Other.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000p0",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000p0",
                    text_content=_TAIL_TRANSCRIPT,
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=1,
                    page_id="P20260401090000p1",
                    keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": null}, {"KEYWORD": " "}]',
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="P20260401090000p1",
                    text_content="Berliner Straße 10 und 日本語メモ。",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=2,
                    page_id="P20260401090000p2",
                    text_content="   ",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=3,
                    page_id="P20260301090000p3",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=102,
                    page_index=0,
                    page_id="P20260401090000del",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageMetadataDO(
                    user_id=2,
                    file_id=103,
                    page_index=0,
                    page_id="P20260401090000u2",
                    keywords_json=_kw_json("optics"),
                ),
            ]
        )
        await session.commit()
    return SearchService(session_manager=session_manager, embedding_model=None)


async def test_search_service_late_bound_embedding_model_adds_semantic_hits(
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    """Keyword search works without embeddings, and late-binding `embedding_model` adds semantic hits."""
    service = SearchService(session_manager=session_manager, embedding_model=None)
    assert service.embedding_model is None

    feline_query_vec = await fake_embedding_model.embed(
        "feline companions", task_type=EmbeddingTaskType.RETRIEVAL_QUERY
    )
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="Pets.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000a",
                    keywords_json=_kw_json("vet-visit"),
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="P20260402090000b",
                    text_content="Cats love sunny windowsills.",
                    embedding=json.dumps(feline_query_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
            ]
        )
        await session.commit()

    tag_hits = await service.search_chunks(user_id=1, query="#vet-visit")
    assert [h.page_index for h in tag_hits] == [0]
    assert await service.search_chunks(user_id=1, query="feline companions") == []

    service.embedding_model = fake_embedding_model
    assert service.embedding_model is fake_embedding_model

    sem_hits = await service.search_chunks(user_id=1, query="feline companions")
    assert [h.page_index for h in sem_hits] == [1]


async def test_search_chunks_degrades_to_lexical_hits_when_embedding_backend_fails(
    session_manager: DatabaseSessionManager,
) -> None:
    service = SearchService(
        session_manager=session_manager,
        embedding_model=_FailingEmbeddingModel(),
    )
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=120,
                    user_id=1,
                    file_name="Resilient.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=120,
                    page_index=0,
                    page_id="P20260401090000ok",
                    keywords_json=_kw_json("optics"),
                ),
            ]
        )
        await session.commit()

    assert await service.search_chunks(user_id=1, query="#optics") == [
        SearchResult(
            file_id=120,
            file_name="Resilient.note",
            page_index=0,
            page_id="P20260401090000ok",
            score=1.0,
            text_preview="Keywords: #optics",
            date="2026-04-01",
        )
    ]


@pytest.mark.parametrize(
    "raw_query",
    [
        "#none",
        " ".join(f"missingword{i}" for i in range(1200)),
    ],
)
async def test_search_chunks_ignores_null_keywords_and_bounds_sql_expression_depth(
    lexical_only_service: SearchService,
    raw_query: str,
) -> None:
    assert await lexical_only_service.search_chunks(user_id=1, query=raw_query) == []


@pytest.mark.parametrize("bad_json", ["{not-json", '"not-a-list"'])
async def test_search_chunks_ignores_malformed_keywords_json(
    session_manager: DatabaseSessionManager,
    bad_json: str,
) -> None:
    service = SearchService(session_manager=session_manager, embedding_model=None)
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=150,
                    user_id=1,
                    file_name="CorruptMeta.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=150,
                    page_index=0,
                    page_id="P20260401090000bad",
                    keywords_json=bad_json,
                ),
            ]
        )
        await session.commit()

    assert await service.search_chunks(user_id=1, query="#optics") == []


async def test_search_chunks_backfills_keyword_snippet_with_escaped_wildcard_and_date_filters(
    lexical_only_service: SearchService,
) -> None:
    hits = await lexical_only_service.search_chunks(
        user_id=1,
        query="#optics",
        top_n=5,
        name_filter="100%_",
        date_after="2026-04-01",
        date_before="2026-04-01",
    )
    expected_preview = f"[#optics] {extract_centered_snippet(_TAIL_TRANSCRIPT, ('optics',), max_len=200 - len('[#optics] '))}"
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="100%_Active.note",
            page_index=0,
            page_id="P20260401090000p0",
            score=1.0,
            text_preview=expected_preview,
            date="2026-04-01",
        )
    ]


async def test_search_chunks_backfills_legacy_empty_page_id_by_page_index(
    session_manager: DatabaseSessionManager,
) -> None:
    service = SearchService(session_manager=session_manager, embedding_model=None)
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=160,
                    user_id=1,
                    file_name="Legacy.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=1,
                    file_id=160,
                    page_index=2,
                    page_id="",
                    keywords_json=_kw_json("optics"),
                ),
                NotePageContentDO(
                    file_id=160,
                    page_index=2,
                    page_id="",
                    text_content="Collimation bench notes.",
                ),
            ]
        )
        await session.commit()

    assert await service.search_chunks(user_id=1, query="#optics", top_n=5) == [
        SearchResult(
            file_id=160,
            file_name="Legacy.note",
            page_index=2,
            page_id="",
            score=1.0,
            text_preview="[#optics] Collimation bench notes.",
            date=None,
        )
    ]


@pytest.mark.parametrize("raw_query", ["日本語", "straße"])
async def test_search_chunks_matches_cjk_and_casefold_transcripts(
    lexical_only_service: SearchService,
    raw_query: str,
) -> None:
    assert await lexical_only_service.search_chunks(user_id=1, query=raw_query) == [
        SearchResult(
            file_id=101,
            file_name="100%_Active.note",
            page_index=1,
            page_id="P20260401090000p1",
            score=0.85,
            text_preview="Berliner Straße 10 und 日本語メモ。",
            date="2026-04-01",
        )
    ]


async def test_search_chunks_matches_halfwidth_katakana_via_nfkc(
    session_manager: DatabaseSessionManager,
) -> None:
    service = SearchService(session_manager=session_manager, embedding_model=None)
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=170,
                    user_id=1,
                    file_name="Halfwidth.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageContentDO(
                    file_id=170,
                    page_index=0,
                    page_id="P20260401090000hw",
                    text_content="ﾊﾝｶｸﾒﾓ",
                ),
            ]
        )
        await session.commit()

    assert await service.search_chunks(user_id=1, query="ﾊﾝｶｸﾒﾓ") == [
        SearchResult(
            file_id=170,
            file_name="Halfwidth.note",
            page_index=0,
            page_id="P20260401090000hw",
            score=0.85,
            text_preview="ﾊﾝｶｸﾒﾓ",
            date="2026-04-01",
        )
    ]


@pytest.mark.parametrize(
    "bad_embedding",
    [
        "",
        "{not-json",
        json.dumps([1.0, 0.0]),
        json.dumps([0.0, 0.0, 0.0]),
    ],
)
async def test_search_chunks_skips_corrupt_or_zero_norm_embeddings(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
    bad_embedding: str,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="Corrupt.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000p0",
                    text_content="Unusable vector",
                    embedding=bad_embedding,
                    embedding_model=fake_embedding_model.model_id,
                ),
            ]
        )
        await session.commit()

    assert await search_service.search_chunks(user_id=1, query="optics") == []


async def test_search_chunks_vector_enforces_similarity_floor_and_emoji_queries(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    rocket_raw = await fake_embedding_model.embed(
        "🚀", task_type=EmbeddingTaskType.RETRIEVAL_QUERY
    )
    opposite_vec = [-v for v in rocket_raw]

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="100%_Vectors.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000p0",
                    text_content="Below similarity floor",
                    embedding=json.dumps(opposite_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="P20260301090000p1",
                    text_content="Before after_date",
                    embedding=json.dumps(rocket_raw),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=2,
                    page_id="P20260401090000p2",
                    text_content="Rocket propulsion calculations.",
                    embedding=json.dumps(rocket_raw),
                    embedding_model=fake_embedding_model.model_id,
                ),
            ]
        )
        await session.commit()

    hits = await search_service.search_chunks(
        user_id=1,
        query="🚀",
        top_n=1,
        name_filter="100%_",
        date_after="2026-04-01",
        date_before="2026-04-01",
    )
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(1.0)
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="100%_Vectors.note",
            page_index=2,
            page_id="P20260401090000p2",
            score=hits[0].score,
            text_preview="Rocket propulsion calculations.",
            date="2026-04-01",
        )
    ]
    assert await search_service.search_chunks(user_id=999, query="🚀", top_n=5) == []


async def test_list_notebooks_escapes_sql_wildcards_and_orders_active_notes(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=201,
                    user_id=1,
                    file_name="100%_Summary.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=1000,
                    update_time=3000,
                ),
                UserFileDO(
                    id=202,
                    user_id=1,
                    file_name="1000XSummary.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=1000,
                    update_time=2000,
                ),
                UserFileDO(
                    id=203,
                    user_id=1,
                    file_name="100%_Deleted.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="N",
                    create_time=1000,
                    update_time=9000,
                ),
            ]
        )
        await session.commit()

    all_notes = await search_service.list_notebooks(user_id=1)
    assert all_notes == [
        NotebookInfo(
            file_id=201,
            file_name="100%_Summary.note",
            create_time=1000,
            update_time=3000,
        ),
        NotebookInfo(
            file_id=202,
            file_name="1000XSummary.note",
            create_time=1000,
            update_time=2000,
        ),
    ]

    escaped = await search_service.list_notebooks(user_id=1, name_filter="100%_")
    assert [n.file_name for n in escaped] == ["100%_Summary.note"]
    assert await search_service.list_notebooks(user_id=1, limit=0) == []
    assert await search_service.list_notebooks(user_id=1, limit=-1) == []


@pytest.mark.parametrize(
    ("query", "top_n", "date_after", "date_before"),
    [
        ("   ", 5, None, None),
        ("###", 5, None, None),
        ("🚀", 5, None, None),
        ("cats", 0, None, None),
        ("cats", -1, None, None),
        ("cats", 5, "not-a-date", None),
        ("cats", 5, "2026-1-5", None),
        ("cats", 5, "2026-05-01", "2026-04-01"),
    ],
)
async def test_search_chunks_guard_clauses(
    search_service: SearchService,
    query: str,
    top_n: int,
    date_after: str | None,
    date_before: str | None,
) -> None:
    assert (
        await search_service.search_chunks(
            user_id=1,
            query=query,
            top_n=top_n,
            date_after=date_after,
            date_before=date_before,
        )
        == []
    )


async def test_hybrid_search_end_to_end_with_synthetic_notebooks_and_noise_floor(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
) -> None:
    """End-to-end hybrid search ranks hybrid > tag-only > semantic and drops unrelated noise."""
    user_id = 1
    hashing_module = PageHashingModule(file_service=file_service)
    token_model = FakeEmbeddingModel(dimensions=128, blended=True)
    service = SearchService(
        session_manager=session_manager, embedding_model=token_model
    )

    unprocessed_nb = build_synthetic_notebook(
        pages=["# Optics Sketch\n\n- Collimation diagram #optics #astronomy"],
        base_date=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        seed=11,
    )
    processed_nb = build_synthetic_notebook(
        pages=[
            "# Mirror Grinding\n\n- Parabolic mirror focal ratio and lens aberration #optics",
            "# Star Party Log\n\n- Checked lens aberration on Jupiter moons",
            "# Grocery Checklist\n\n- Buy laundry detergent, bananas, and dish soap",
        ],
        base_date=datetime(2026, 3, 12, 9, 0, tzinfo=UTC),
        seed=22,
    )

    for fid, fname, synth in [
        (401, "Unprocessed_Sketch.note", unprocessed_nb),
        (402, "Optics_Lab.note", processed_nb),
    ]:
        skey = f"hybrid-{fid}.note"
        await file_service.blob_storage.put(USER_DATA_BUCKET, skey, synth.data)
        async with session_manager.session() as session:
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=user_id,
                    directory_id=0,
                    file_name=fname,
                    is_folder="N",
                    is_active="Y",
                    storage_key=skey,
                    md5=hashlib.md5(synth.data).hexdigest(),
                    size=len(synth.data),
                )
            )
            await session.commit()
        await hashing_module.process(fid, session_manager)

    async with session_manager.session() as session:
        for page in processed_nb.pages:
            vec = await token_model.embed(
                page.text, task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
            )
            content_row = (
                await session.execute(
                    select(NotePageContentDO).where(
                        NotePageContentDO.file_id == 402,
                        NotePageContentDO.page_id == page.page_id,
                    )
                )
            ).scalar_one()
            content_row.text_content = page.text
            content_row.embedding = json.dumps(vec)
            content_row.embedding_model = token_model.model_id
        await session.commit()

    ranked = await service.search_chunks(
        user_id=user_id, query="#optics aberration", top_n=5
    )
    top_one = await service.search_chunks(
        user_id=user_id, query="#optics aberration", top_n=1
    )
    assert top_one == ranked[:1]
    assert len(ranked) == 3
    assert ranked[0].score > ranked[1].score > ranked[2].score >= 0.25
    assert ranked == [
        SearchResult(
            file_id=402,
            file_name="Optics_Lab.note",
            page_index=0,
            page_id=processed_nb.pages[0].page_id,
            score=ranked[0].score,
            text_preview=processed_nb.pages[0].text.strip(),
            date="2026-03-12",
        ),
        SearchResult(
            file_id=401,
            file_name="Unprocessed_Sketch.note",
            page_index=0,
            page_id=unprocessed_nb.pages[0].page_id,
            score=ranked[1].score,
            text_preview="Keywords: #optics, #astronomy",
            date="2026-03-10",
        ),
        SearchResult(
            file_id=402,
            file_name="Optics_Lab.note",
            page_index=1,
            page_id=processed_nb.pages[1].page_id,
            score=ranked[2].score,
            text_preview=processed_nb.pages[1].text.strip(),
            date="2026-03-13",
        ),
    ]
