import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.search import SearchService


@pytest.fixture
def mock_gemini_service() -> MagicMock:
    service = MagicMock()
    service.is_configured = True
    service.embed_content = AsyncMock()
    return service


@pytest.fixture
def search_service(
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
    server_config: ServerConfig,
) -> SearchService:
    server_config.gemini_embedding_model = "text-embedding-004"
    return SearchService(
        session_manager=session_manager,
        gemini_service=mock_gemini_service,
        config=server_config,
    )


async def test_search_chunks_success(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 1
    file_id_1 = 101
    file_id_2 = 102

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
                embedding=json.dumps([1.0, 0.0, 0.0]),
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id_2,
                page_index=0,
                page_id="p0",
                text_content="This is the second chunk about dogs.",
                embedding=json.dumps([0.0, 1.0, 0.0]),
            )
        )
        await session.commit()

    # Mock Gemini Embedding for query "cats"
    mock_response = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [1.0, 0.0, 0.0]
    mock_response.embeddings = [mock_embedding]
    mock_gemini_service.embed_content.return_value = mock_response

    # Run Search
    results = await search_service.search_chunks(user_id=user_id, query="cats", top_n=5)

    # Verifications
    assert len(results) == 2
    assert results[0].file_id == file_id_1
    assert results[0].score > 0.99
    assert "cats" in results[0].text_preview
    assert results[1].file_id == file_id_2
    assert results[1].score < 0.01


async def test_search_chunks_with_name_filter(
    search_service: SearchService,
    session_manager: DatabaseSessionManager,
    mock_gemini_service: MagicMock,
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
                embedding=json.dumps([1.0, 0.0]),
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id_2,
                page_index=0,
                page_id="p0",
                text_content="Dogs are great.",
                embedding=json.dumps([1.0, 0.0]),
            )
        )
        await session.commit()

    # Mock Gemini Embedding
    mock_response = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [1.0, 0.0]
    mock_response.embeddings = [mock_embedding]
    mock_gemini_service.embed_content.return_value = mock_response

    # Run Search with name filter "Monthly"
    results = await search_service.search_chunks(
        user_id=user_id, query="anything", name_filter="Monthly"
    )

    # Verifications
    assert len(results) == 1
    assert results[0].file_name == "Monthly Plan.note"
