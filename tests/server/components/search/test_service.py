"""Unit tests for `supernote.server.components.search.service.SearchService`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.search import (
    NotebookInfo,
    SearchResult,
    SearchService,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager


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
def fake_embedding_model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel()


@pytest.fixture
def search_service(
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> SearchService:
    return SearchService(
        session_manager=session_manager,
        embedding_model=fake_embedding_model,
    )


async def test_search_service_late_bound_embedding_model_enables_search(
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    """Verify binding `service.embedding_model` after initialization activates vector search."""
    service = SearchService(session_manager=session_manager, embedding_model=None)
    assert service.embedding_model is None

    cats_vec = await fake_embedding_model.embed(
        "cats", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
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
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P20260401090000a",
                    text_content="Cats love sunny windowsills.",
                    embedding=json.dumps(cats_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
            ]
        )
        await session.commit()

    assert await service.search_chunks(user_id=1, query="cats") == []

    service.embedding_model = fake_embedding_model
    assert service.embedding_model is fake_embedding_model

    hits = await service.search_chunks(user_id=1, query="cats")
    assert len(hits) == 1
    assert hits == [
        SearchResult(
            file_id=101,
            file_name="Pets.note",
            page_index=0,
            page_id="P20260401090000a",
            score=hits[0].score,
            text_preview="Cats love sunny windowsills.",
            date="2026-04-01",
        )
    ]


async def test_search_chunks_returns_empty_on_embedding_backend_error(
    session_manager: DatabaseSessionManager,
) -> None:
    service = SearchService(
        session_manager=session_manager,
        embedding_model=_FailingEmbeddingModel(),
    )
    assert await service.search_chunks(user_id=1, query="optics") == []


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


async def test_search_chunks_filters_note_files_dates_escaped_wildcards_and_users(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    rocket_vec = await fake_embedding_model.embed(
        "🚀", task_type=EmbeddingTaskType.RETRIEVAL_QUERY
    )
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
                UserFileDO(
                    id=102,
                    user_id=1,
                    file_name="100%_Document.pdf",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P20260402090000p0",
                    text_content="After before_date",
                    embedding=json.dumps(rocket_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=1,
                    page_id="P20260301090000p1",
                    text_content="Before after_date",
                    embedding=json.dumps(rocket_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=2,
                    page_id="P20260401090000p2",
                    text_content="Rocket propulsion calculations.",
                    embedding=json.dumps(rocket_vec),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=102,
                    page_index=0,
                    page_id="P20260401090000pdf",
                    text_content="Non-note file should be ignored.",
                    embedding=json.dumps(rocket_vec),
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
