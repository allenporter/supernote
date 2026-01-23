import os
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.mcp.server import get_notebook_transcript, search_notebook_chunks
from supernote.server.services.search import SearchResult


@pytest.fixture
def mock_env() -> Generator[None, None, None]:
    with patch.dict(
        os.environ, {"SUPERNOTE_TOKEN": "fake-token", "SUPERNOTE_CONFIG_DIR": "/tmp"}
    ):
        yield


@pytest.fixture
def mock_services() -> Generator[tuple[AsyncMock, AsyncMock], None, None]:
    mock_user_service = AsyncMock()
    mock_search_service = AsyncMock()

    # Directly update the _services dict in the module
    services = {
        "user_service": mock_user_service,
        "search_service": mock_search_service,
    }
    with patch.dict("supernote.mcp.server._services", services):
        yield mock_user_service, mock_search_service


@pytest.mark.asyncio
async def test_search_notebook_chunks_tool(
    mock_env: None, mock_services: tuple[AsyncMock, AsyncMock]
) -> None:
    mock_user_service, mock_search_service = mock_services

    # Mock Auth
    mock_user_service.verify_token.return_value = MagicMock(email="test@example.com")
    mock_user_service.get_user_id.return_value = 100

    # Use real SearchResult dataclass instead of MagicMock so asdict() works
    result = SearchResult(
        file_id=1,
        file_name="Journal.note",
        page_index=0,
        page_id="p1",
        score=0.95,
        text_preview="Today I learned...",
        date="2023-10-27",
    )

    mock_search_service.search_chunks.return_value = [result]

    # Call Tool
    response = await search_notebook_chunks(query="test")

    assert response["success"] is True
    results = response["results"]
    assert len(results) == 1
    assert results[0]["fileName"] == "Journal.note"
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_get_notebook_transcript_tool(
    mock_env: None, mock_services: tuple[AsyncMock, AsyncMock]
) -> None:
    mock_user_service, mock_search_service = mock_services

    # Mock Auth
    mock_user_service.verify_token.return_value = MagicMock(email="test@example.com")
    mock_user_service.get_user_id.return_value = 100

    # Mock Transcript
    mock_search_service.get_transcript.return_value = "Full transcript content"

    # Call Tool
    response = await get_notebook_transcript(file_id=123)

    assert response["success"] is True
    assert response["transcript"] == "Full transcript content"


@pytest.mark.asyncio
async def test_tools_unauthorized(
    mock_env: None, mock_services: tuple[AsyncMock, AsyncMock]
) -> None:
    mock_user_service, _ = mock_services

    # Mock Auth Failure
    mock_user_service.verify_token.return_value = None

    # Call Tool
    response = await search_notebook_chunks(query="test")

    assert response["success"] is False
    assert "Authentication failed" in response["errorMsg"]
    assert response["errorCode"] == "401"
