import json

import pytest

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.search import SearchService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
)
from supernote.server.db.session import DatabaseSessionManager


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
