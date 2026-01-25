import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def setup_service(client: Any) -> AsyncGenerator[None, None]:
    """Setup the MCP service."""
    yield


@pytest.fixture
def mcp_url(server_config: ServerConfig) -> str:
    """Get the MCP URL."""
    # Ensure host is localhost for security checks
    server_config.host = "127.0.0.1"
    return f"http://{server_config.host}:{server_config.mcp_port}/mcp"


@pytest.fixture
async def notebook_file_id(
    create_test_user: Any, session_manager: DatabaseSessionManager
) -> int:
    """Fixture to populate the database with test data."""
    async with session_manager.session() as db:
        # Get the default test user created by create_test_user fixture
        user_result = await db.execute(
            select(UserDO).where(UserDO.email == "test@example.com")
        )
        user = user_result.scalar_one()
        user_id = user.id

        # Add a fake note file
        file_do = UserFileDO(
            user_id=user_id,
            directory_id=0,
            file_name="test_notes.note",
            storage_key="test_notes_storage_key",
        )
        db.add(file_do)
        await db.flush()

        # Add content for search
        content_do = NotePageContentDO(
            file_id=file_do.id,
            page_index=0,
            page_id="P001",
            text_content="This is a test note.",
            embedding=json.dumps([0.1] * 768),
        )
        db.add(content_do)
        await db.commit()
        return int(file_do.id)


@pytest.fixture
def mock_gemini_service() -> Generator[None, None, None]:
    """Fixture to mock Gemini service."""
    # 1. Mock Gemini Service to avoid network calls
    mock_embedding_response = AsyncMock()
    mock_embedding_response.embeddings = [AsyncMock(values=[0.1] * 768)]

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


@asynccontextmanager
async def mcp_session(
    mcp_url: str, auth_headers: dict[str, str]
) -> AsyncGenerator[ClientSession, None]:
    """Helper context manager for MCP sessions to avoid AnyIO task group leaks in fixtures."""
    async with httpx.AsyncClient(headers=auth_headers) as http_client:
        # Wait a moment for server to be ready
        await asyncio.sleep(0.5)
        async with streamable_http_client(mcp_url, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


@pytest.mark.asyncio
async def test_mcp_list_tools(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for listing MCP tools."""
    async with mcp_session(mcp_url, auth_headers) as session:
        result = await session.list_tools()
        tool_names = [t.name for t in result.tools]
        assert "search_notebook_chunks" in tool_names
        assert "get_notebook_transcript" in tool_names


@pytest.mark.asyncio
async def test_mcp_search_notebook_chunks(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for searching notebook chunks."""
    token = auth_headers["x-access-token"]
    async with mcp_session(mcp_url, auth_headers) as session:
        call_result = await session.call_tool(
            "search_notebook_chunks",
            arguments={"query": "test"},
            meta={"token": token},
        )

        assert call_result.content
        content = call_result.content[0]
        assert isinstance(content, TextContent)
        res_data = json.loads(content.text)
        assert "results" in res_data
        assert len(res_data["results"]) > 0
        assert res_data["results"][0].get("textPreview") == "This is a test note."


@pytest.mark.asyncio
async def test_mcp_get_notebook_transcript(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for getting a notebook transcript."""
    token = auth_headers["x-access-token"]
    async with mcp_session(mcp_url, auth_headers) as session:
        transcript_result = await session.call_tool(
            "get_notebook_transcript",
            arguments={"file_id": notebook_file_id},
            meta={"token": token},
        )
        assert transcript_result.content
        content = transcript_result.content[0]
        assert isinstance(content, TextContent)
        trans_data = json.loads(content.text)
        assert "This is a test note." in trans_data.get("transcript", "")


@pytest.mark.asyncio
async def test_mcp_unauthorized(
    mcp_url: str,
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for MCP tools with invalid authentication."""
    # Use invalid headers
    invalid_headers = {"x-access-token": "invalid-token"}
    async with mcp_session(mcp_url, invalid_headers) as session:
        # Call tool
        call_result = await session.call_tool(
            "search_notebook_chunks",
            arguments={"query": "test"},
            meta={"token": "invalid-token"},
        )

        # Verify failure response (based on create_error_response in server.py)
        assert call_result.content
        content = call_result.content[0]
        assert isinstance(content, TextContent)
        res_data = json.loads(content.text)
        assert res_data["success"] is False
        assert res_data["errorCode"] == "401"
        assert "Authentication failed" in res_data["errorMsg"]
