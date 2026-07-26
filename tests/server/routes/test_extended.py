from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from supernote.client.client import Client
from supernote.client.extended import ExtendedClient
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager


@pytest.fixture
def extended_client(authenticated_client: Client) -> ExtendedClient:
    """Fixture for ExtendedClient."""
    return ExtendedClient(authenticated_client)


@pytest.fixture
def mock_gemini_service() -> Generator[None, None, None]:
    """Fixture to mock Gemini service."""
    # Mock Gemini Service to avoid network calls
    mock_embedding_response = AsyncMock()
    mock_embedding_response.embeddings = [AsyncMock(values=[1.0, 0.0, 0.0])]

    with (
        patch(
            "supernote.server.services.gemini.GeminiService.is_configured",
            return_value=True,
        ),
        patch(
            "supernote.server.services.gemini.GeminiService.embed_content",
            return_value=mock_embedding_response,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def patch_gemini_service(mock_gemini_service: Generator[None, None, None]) -> None:
    """Patch the Gemini service in the search service."""
    # This is handled by the mock_gemini_service fixture
    pass


async def test_extended_search(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
) -> None:
    # 1. Seed some search data
    user_id = 1
    file_id = 101
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="SearchTest.note", directory_id=0
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                text_content="The quick brown fox jumps over the lazy dog.",
                # Mock embedding [1, 0, 0] for simplicity in SQL
                embedding="[1.0, 0.0, 0.0]",
            )
        )
        await session.commit()

    resp = await extended_client.get_transcript(file_id=file_id)
    assert resp.success
    assert resp.transcript is not None
    assert "quick brown fox" in resp.transcript


async def test_extended_search_with_mock(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    client: Any,  # TestClient from aiohttp
) -> None:
    # 1. Seed data
    user_id = 1
    file_id = 101
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="Fox.note", directory_id=0
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                text_content="The quick brown fox.",
                embedding="[1.0, 0.0, 0.0]",
            )
        )
        await session.commit()

    # 2. Call API
    # The Gemini service is mocked globally by mock_gemini_service
    resp = await extended_client.search(query="fox")

    assert resp.success
    assert len(resp.results) > 0
    assert resp.results[0].file_id == file_id
    assert "quick brown fox" in resp.results[0].text_preview


async def test_extended_transcript_not_found(
    extended_client: ExtendedClient,
) -> None:
    # Request transcript for non-existent file
    with pytest.raises(Exception):  # The client raises for 404
        await extended_client.get_transcript(file_id=999)
