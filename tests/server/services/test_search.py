import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.search import PageTranscript, SearchResult, SearchService
from supernote.server.services.user import UserService
from supernote.testing.notebook_fixtures import build_synthetic_notebook


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


async def test_search_chunks_success(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    # Setup Data
    user_id = 1
    file_id_1 = 101
    file_id_2 = 102
    cats_vec = await fake_embedding_model.embed(
        "cats", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )
    orthogonal_vec = [cats_vec[1], -cats_vec[0], 0.0]

    async with session_manager.session() as session:
        # Files
        session.add(
            UserFileDO(
                id=file_id_1, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )
        session.add(
            UserFileDO(
                id=file_id_2,
                user_id=user_id,
                file_name="Monthly Plan.note",
                directory_id=0,
            )
        )

        # Chunks with embeddings
        session.add(
            NotePageContentDO(
                file_id=file_id_1,
                page_index=0,
                page_id="p0",
                text_content="This is the first chunk about cats.",
                embedding=json.dumps(cats_vec),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id_2,
                page_index=0,
                page_id="p0",
                text_content="This is the second chunk about dogs.",
                embedding=json.dumps(orthogonal_vec),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        await session.commit()

    # Run Search
    results = await search_service.search_chunks(user_id=user_id, query="cats", top_n=5)

    # Verifications
    assert len(results) == 2
    assert results[0].file_id == file_id_1
    assert results[0].score > 0.99
    assert "cats" in results[0].text_preview
    assert results[1].file_id == file_id_2
    assert abs(results[1].score) < 0.01


async def test_search_chunks_inactive_file(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    # Setup Data
    user_id = 1
    active_file_id = 101
    deleted_file_id = 102

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=active_file_id,
                user_id=user_id,
                file_name="Active.note",
                directory_id=0,
                is_active="Y",
            )
        )
        session.add(
            UserFileDO(
                id=deleted_file_id,
                user_id=user_id,
                file_name="Deleted.note",
                directory_id=0,
                is_active="N",
            )
        )

        session.add(
            NotePageContentDO(
                file_id=active_file_id,
                page_index=0,
                page_id="p0",
                text_content="Cats are active pets.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=deleted_file_id,
                page_index=0,
                page_id="p0",
                text_content="Cats were deleted pets.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        await session.commit()

    results = await search_service.search_chunks(user_id=user_id, query="cats", top_n=5)

    assert len(results) == 1
    assert results[0].file_id == active_file_id
    assert results[0].file_name == "Active.note"


async def test_search_chunks_with_name_filter(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    # Setup Data
    user_id = 1
    file_id_1 = 101
    file_id_2 = 102

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id_1, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )
        session.add(
            UserFileDO(
                id=file_id_2,
                user_id=user_id,
                file_name="Monthly Plan.note",
                directory_id=0,
            )
        )

        session.add(
            NotePageContentDO(
                file_id=file_id_1,
                page_index=0,
                page_id="p0",
                text_content="Cats are great.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id_2,
                page_index=0,
                page_id="p0",
                text_content="Dogs are great.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        await session.commit()

    # Run Search with name filter "Monthly"
    results = await search_service.search_chunks(
        user_id=user_id, query="anything", name_filter="Monthly"
    )

    # Verifications
    assert len(results) == 1
    assert results[0].file_name == "Monthly Plan.note"


async def test_get_transcript(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
) -> None:
    # Setup Data
    user_id = 1
    file_id = 101

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )

        # Two pages with date-encoded IDs
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Page 1 content.",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P20231028120000def",
                text_content="Page 2 content.",
            )
        )
        await session.commit()

    # Full transcript
    transcript = await search_service.get_transcript(user_id=user_id, file_id=file_id)
    assert transcript is not None
    assert "Page 1 content." in transcript
    assert "Page 2 content." in transcript
    assert "--- Page 1 ---" in transcript
    assert "Notebook Filename: Journal.note" in transcript
    assert "Page ID: P20231027120000abc" in transcript
    assert "Page Date (Inferred): 2023-10-27" in transcript
    assert "Page Date (Inferred): 2023-10-28" in transcript

    # Specific page
    page1 = await search_service.get_transcript(
        user_id=user_id, file_id=file_id, page_index=0
    )
    assert page1 == "Page 1 content."

    # Unauthorized
    assert await search_service.get_transcript(user_id=99, file_id=file_id) is None

    # Page range (Page 2 only via range)
    range_trans = await search_service.get_transcript(
        user_id=user_id, file_id=file_id, start_index=1, end_index=1
    )
    assert range_trans is not None
    assert "Page 2 content." in range_trans
    assert "Page 1 content." not in range_trans
    assert "--- Page 2 ---" in range_trans
    assert "Page ID: P20231028120000def" in range_trans

    # Structured per-page transcripts
    page_transcripts = await search_service.get_page_transcripts(
        user_id=user_id, file_id=file_id
    )
    assert page_transcripts == [
        PageTranscript(
            page_index=0,
            page_id="P20231027120000abc",
            text="Page 1 content.",
            date="2023-10-27",
        ),
        PageTranscript(
            page_index=1,
            page_id="P20231028120000def",
            text="Page 2 content.",
            date="2023-10-28",
        ),
    ]

    # Structured per-page transcripts with range filter
    range_pages = await search_service.get_page_transcripts(
        user_id=user_id, file_id=file_id, start_index=1, end_index=1
    )
    assert range_pages == [
        PageTranscript(
            page_index=1,
            page_id="P20231028120000def",
            text="Page 2 content.",
            date="2023-10-28",
        ),
    ]

    # Unauthorized structured per-page transcripts
    assert await search_service.get_page_transcripts(user_id=99, file_id=file_id) == []

    # Soft-deleted notebook and unprocessed notebook (no OCR text yet)
    deleted_file_id = 102
    unprocessed_file_id = 103
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=deleted_file_id,
                    user_id=user_id,
                    file_name="Deleted.note",
                    directory_id=0,
                    is_active="N",
                ),
                NotePageContentDO(
                    file_id=deleted_file_id,
                    page_index=0,
                    page_id="p0",
                    text_content="Deleted content",
                ),
                UserFileDO(
                    id=unprocessed_file_id,
                    user_id=user_id,
                    file_name="Pending.note",
                    directory_id=0,
                    is_active="Y",
                ),
                NotePageContentDO(
                    file_id=unprocessed_file_id,
                    page_index=0,
                    page_id="p0",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    assert (
        await search_service.get_transcript(user_id=user_id, file_id=deleted_file_id)
        is None
    )
    assert (
        await search_service.get_page_transcripts(
            user_id=user_id, file_id=deleted_file_id
        )
        == []
    )
    assert (
        await search_service.get_transcript(
            user_id=user_id, file_id=unprocessed_file_id
        )
        is None
    )
    assert (
        await search_service.get_page_transcripts(
            user_id=user_id, file_id=unprocessed_file_id
        )
        == []
    )


async def test_search_chunks_with_date_filter_inferred(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    # Setup Data
    user_id = 1
    file_id = 101

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )

        # Page from 2023-10-27
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Page 1 content.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        # Page from 2023-10-28
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P20231028120000def",
                text_content="Page 2 content.",
                embedding=json.dumps([1.0, 0.0, 0.0]),
                embedding_model=fake_embedding_model.model_id,
            )
        )
        await session.commit()

    # Filter for Oct 27
    results = await search_service.search_chunks(
        user_id=user_id, query="test", date_after="2023-10-27", date_before="2023-10-27"
    )
    assert len(results) == 1
    assert results[0].page_index == 0
    assert results[0].date == "2023-10-27"

    # Filter for Oct 28
    results = await search_service.search_chunks(
        user_id=user_id, query="test", date_after="2023-10-28"
    )
    assert len(results) == 1
    assert results[0].page_index == 1

    # Filter for range
    results = await search_service.search_chunks(
        user_id=user_id, query="test", date_after="2023-10-27", date_before="2023-10-29"
    )
    assert len(results) == 2


async def test_search_chunks_filters_by_embedding_model(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    """Verify search_chunks ignores pages embedded with a different model or None."""
    user_id = 1
    file_id = 101

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    text_content="Matching model page.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model=fake_embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p1",
                    text_content="Other model page with different dimensions.",
                    embedding=json.dumps([1.0] * 768),
                    embedding_model="gemini-embedding-001",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=2,
                    page_id="p2",
                    text_content="Unannotated model page.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model=None,
                ),
            ]
        )
        await session.commit()

    results = await search_service.search_chunks(user_id=user_id, query="test", top_n=5)
    assert len(results) == 1
    assert results[0].page_index == 0
    assert results[0].text_preview == "Matching model page."


async def test_list_notebooks(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 1
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=user_id,
                    file_name="Older.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=1000,
                    update_time=1500,
                ),
                UserFileDO(
                    id=102,
                    user_id=user_id,
                    file_name="Newer_Daily.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=2000,
                    update_time=3000,
                ),
                UserFileDO(
                    id=103,
                    user_id=user_id,
                    file_name="Deleted.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="N",
                    create_time=4000,
                    update_time=5000,
                ),
                UserFileDO(
                    id=104,
                    user_id=user_id,
                    file_name="Document.pdf",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=4000,
                    update_time=5000,
                ),
                UserFileDO(
                    id=105,
                    user_id=999,
                    file_name="OtherUser.note",
                    directory_id=0,
                    is_folder="N",
                    is_active="Y",
                    create_time=4000,
                    update_time=5000,
                ),
            ]
        )
        await session.commit()

    notebooks = await search_service.list_notebooks(user_id=user_id)
    assert [n.file_id for n in notebooks] == [102, 101]
    assert notebooks[0].file_name == "Newer_Daily.note"
    assert notebooks[0].create_time == 2000
    assert notebooks[0].update_time == 3000

    filtered = await search_service.list_notebooks(user_id=user_id, name_filter="daily")
    assert [n.file_id for n in filtered] == [102]

    limited = await search_service.list_notebooks(user_id=user_id, limit=1)
    assert [n.file_id for n in limited] == [102]


async def test_get_transcript_includes_verified_page_keywords(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify get_transcript includes Page Keywords only for matching (page_id, content_hash) metadata rows."""
    user_id = 1
    file_id = 199

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                file_name="Architecture.note",
                directory_id=0,
                is_active="Y",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20260301090000a",
                content_hash="h_arch",
                text_content="Discussed schema design.",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=user_id,
                file_id=file_id,
                page_index=0,
                page_id="P20260301090000a",
                content_hash="h_arch",
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "SQLite"}]',
            )
        )
        await session.commit()

    transcript = await search_service.get_transcript(user_id=user_id, file_id=file_id)
    assert transcript is not None
    assert "Page Keywords: SQLite" in transcript


class _TokenEmbeddingModel(EmbeddingModel):
    """Deterministic per-token test embedding model with graded overlap similarity."""

    def __init__(self, dimensions: int = 64, model_id: str = "test-token-v1") -> None:
        self._dimensions = dimensions
        self._model_id = model_id

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        tokens = [t.strip("#.,:;!?").lower() for t in text.split()]
        tokens = [t for t in tokens if t] or [text]
        vec = [0.0] * self._dimensions
        for tok in tokens:
            digest = hashlib.sha256(tok.encode()).digest()
            for i in range(self._dimensions):
                vec[i] += (digest[i % len(digest)] / 127.5) - 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


async def test_search_chunks_keyword_only_without_embedding_model(
    session_manager: DatabaseSessionManager,
) -> None:
    """Keyword search matches native keywords and OCR text when `embedding_model` is `None`."""
    user_id = 1
    service = SearchService(session_manager=session_manager, embedding_model=None)

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=201,
                    user_id=user_id,
                    file_name="Sketchbook.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                UserFileDO(
                    id=202,
                    user_id=user_id,
                    file_name="FieldLog.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                UserFileDO(
                    id=203,
                    user_id=999,
                    file_name="OtherUser.note",
                    directory_id=0,
                    is_active="Y",
                    is_folder="N",
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=201,
                    page_index=0,
                    page_id="P20260401090000abc",
                    keywords_json=json.dumps(
                        [{"KEYWORDPAGE": "1", "KEYWORD": "ks-tilt"}]
                    ),
                ),
                NotePageContentDO(
                    file_id=202,
                    page_index=1,
                    page_id="P20260402090000def",
                    text_content="Verified ks-tilt stylus response.",
                ),
                NotePageMetadataDO(
                    user_id=999,
                    file_id=203,
                    page_index=0,
                    page_id="P20260401090000xyz",
                    keywords_json=json.dumps(
                        [{"KEYWORDPAGE": "1", "KEYWORD": "ks-tilt"}]
                    ),
                ),
            ]
        )
        await session.commit()

    results = await service.search_chunks(user_id=user_id, query="#KS-Tilt", top_n=5)
    assert results == [
        SearchResult(
            file_id=201,
            file_name="Sketchbook.note",
            page_index=0,
            page_id="P20260401090000abc",
            score=1.0,
            text_preview="Keywords: #ks-tilt",
            date="2026-04-01",
        ),
        SearchResult(
            file_id=202,
            file_name="FieldLog.note",
            page_index=1,
            page_id="P20260402090000def",
            score=0.85,
            text_preview="Verified ks-tilt stylus response.",
            date="2026-04-02",
        ),
    ]


@pytest.mark.parametrize(
    ("query", "top_n", "date_after", "date_before"),
    [
        ("###", 5, None, None),
        ("   ", 5, None, None),
        ("---", 5, None, None),
        ("#ks-tilt", 0, None, None),
        ("#ks-tilt", -1, None, None),
        ("#ks-tilt", 5, "2026-05-01", "2026-04-01"),
        ("#ks-tilt", 5, "not-a-date", None),
    ],
)
async def test_search_chunks_guard_clauses(
    session_manager: DatabaseSessionManager,
    query: str,
    top_n: int,
    date_after: str | None,
    date_before: str | None,
) -> None:
    service = SearchService(session_manager=session_manager, embedding_model=None)
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=210,
                user_id=1,
                file_name="Sketch.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=1,
                file_id=210,
                page_index=0,
                page_id="P20260415090000abc",
                keywords_json=json.dumps([{"KEYWORDPAGE": "1", "KEYWORD": "ks-tilt"}]),
            )
        )
        await session.commit()

    assert (
        await service.search_chunks(
            user_id=1,
            query=query,
            top_n=top_n,
            date_after=date_after,
            date_before=date_before,
        )
        == []
    )


async def test_search_chunks_post_init_embedding_model_rebind(
    session_manager: DatabaseSessionManager,
) -> None:
    """Assigning `search_service.embedding_model` after init updates the vector searcher."""
    user_id = 1
    service = SearchService(session_manager=session_manager, embedding_model=None)
    token_model = _TokenEmbeddingModel()
    doc_text = "Observing celestial constellations and nebulae"
    doc_vec = await token_model.embed(
        doc_text, task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=301,
                user_id=user_id,
                file_name="NightSky.note",
                directory_id=0,
                is_active="Y",
                is_folder="N",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=301,
                page_index=0,
                page_id="P20260410220000abc",
                text_content=doc_text,
                embedding=json.dumps(doc_vec),
                embedding_model=token_model.model_id,
            )
        )
        await session.commit()

    assert await service.search_chunks(user_id=user_id, query="celestial galaxy") == []

    service.embedding_model = token_model
    assert service.embedding_model is token_model

    hits = await service.search_chunks(user_id=user_id, query="celestial galaxy")
    assert len(hits) == 1
    assert hits[0].file_id == 301
    assert 0.25 < hits[0].score < 0.85


async def test_hybrid_search_end_to_end_with_synthetic_notebooks(
    session_manager: DatabaseSessionManager,
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
) -> None:
    """End-to-end hybrid ranking across synthetic `.note` files hashed via `PageHashingModule`."""
    user_id = 1
    file_service = FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
    )
    hashing_module = PageHashingModule(file_service=file_service)
    token_model = _TokenEmbeddingModel()
    service = SearchService(
        session_manager=session_manager, embedding_model=token_model
    )

    unprocessed_nb = build_synthetic_notebook(
        pages=[
            "# Optics Sketch\n\n- Collimation diagram #optics #astronomy",
        ],
        base_date=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        seed=11,
    )
    processed_nb = build_synthetic_notebook(
        pages=[
            "# Mirror Grinding\n\n- Parabolic mirror focal ratio and lens aberration #optics",
            "# Star Party Log\n\n- Checked lens aberration on Jupiter moons",
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
    assert [(r.file_id, r.page_index) for r in ranked] == [
        (402, 0),
        (401, 0),
        (402, 1),
    ]
    assert ranked[0].score > ranked[1].score > ranked[2].score > 0.15
    assert "Parabolic mirror" in ranked[0].text_preview
    assert ranked[1].text_preview == "Keywords: #optics, #astronomy"
    assert ranked[1].date == "2026-03-10"
