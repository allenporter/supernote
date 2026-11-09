import json
import logging
import re
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from prometheus_client import REGISTRY
from sqlalchemy import select

from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import SEARCH_SERVICE_KEY

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mcp_url(server_config: ServerConfig, client: Any) -> str:
    """Get the MCP URL."""
    # Ensure host is localhost for security checks
    server_config.host = "127.0.0.1"
    return f"http://{server_config.host}:{server_config.mcp_port}/mcp"


@pytest.fixture
async def setup_service(client: Any) -> AsyncGenerator[None]:
    """Setup the MCP service."""
    yield


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
            embedding_model="fake-embedding-v1",
        )
        db.add(content_do)
        await db.commit()
        return int(file_do.id)


@pytest.fixture
def mock_gemini_service(client: Any) -> Generator[None]:
    """Fixture to configure a FakeEmbeddingModel on the app's search service."""
    search_service = client.app[SEARCH_SERVICE_KEY]
    original = search_service.embedding_model
    search_service.embedding_model = FakeEmbeddingModel(dimensions=768)
    try:
        yield
    finally:
        search_service.embedding_model = original


@asynccontextmanager
async def mcp_session(
    mcp_url: str, auth_headers: dict[str, str]
) -> AsyncGenerator[ClientSession]:
    """Helper context manager for MCP sessions to avoid AnyIO task group leaks in fixtures."""
    async with httpx2.AsyncClient(headers=auth_headers) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as res:
            read_stream, write_stream = res[0], res[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def test_mcp_list_tools(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for listing MCP tools which does not require auth."""
    async with mcp_session(mcp_url, auth_headers) as session:
        result = await session.list_tools()
        tool_names = [t.name for t in result.tools]
        assert "list_notebooks" in tool_names
        assert "search_notebook_chunks" in tool_names
        assert "get_notebook_transcript" in tool_names


async def test_mcp_list_notebooks(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
) -> None:
    """Integrated test for listing notebooks via MCP."""
    token = auth_headers["x-access-token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with mcp_session(mcp_url, headers) as session:
        call_result = await session.call_tool(
            "list_notebooks",
            arguments={"name_filter": "test_notes"},
            meta={"token": token},
        )
        assert call_result.content
        content = call_result.content[0]
        assert isinstance(content, TextContent)
        res_data = json.loads(content.text)
        assert len(res_data["notebooks"]) == 1
        assert res_data["notebooks"][0]["fileId"] == str(notebook_file_id)
        assert res_data["notebooks"][0]["fileName"] == "test_notes.note"


async def test_mcp_search_notebook_chunks(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for searching notebook chunks."""
    token = auth_headers["x-access-token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with mcp_session(mcp_url, headers) as session:
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
        assert res_data["results"][0]["fileId"] == str(notebook_file_id)
        assert res_data["results"][0].get("textPreview") == "This is a test note."


async def test_mcp_get_notebook_transcript(
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
    mock_gemini_service: Any,
) -> None:
    """Integrated test for getting a notebook transcript."""
    token = auth_headers["x-access-token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with mcp_session(mcp_url, headers) as session:
        transcript_result = await session.call_tool(
            "get_notebook_transcript",
            arguments={"file_id": str(notebook_file_id)},
            meta={"token": token},
        )
        assert transcript_result.content
        content = transcript_result.content[0]
        assert isinstance(content, TextContent)
        trans_data = json.loads(content.text)
        assert "This is a test note." in trans_data.get("transcript", "")


async def test_mcp_unauthorized(
    mcp_url: str,
    notebook_file_id: int,
    mock_gemini_service: Any,
    server_config: ServerConfig,
) -> None:
    """Integrated test for MCP tools with invalid authentication."""
    # Use invalid headers
    invalid_headers = {"Authorization": "Bearer invalid-token"}

    # Standard MCP client will fail during stream connection or initialization
    with pytest.raises(ExceptionGroup):
        async with mcp_session(mcp_url, invalid_headers):
            pass

    # Direct request returns HTTP 401 with WWW-Authenticate header
    async with httpx2.AsyncClient() as client:
        resp = await client.post(mcp_url, headers=invalid_headers)
        assert resp.status_code == 401
        assert "www-authenticate" in resp.headers
        auth_header = resp.headers["www-authenticate"]
        assert "error_description=" in auth_header
        assert "resource_metadata=" in auth_header

        # Extract metadata URL from WWW-Authenticate header
        match = re.search(r'resource_metadata="([^"]+)"', auth_header)
        assert match, (
            f"WWW-Authenticate header missing resource_metadata: {auth_header}"
        )
        metadata_url = match.group(1)

        meta_response = await client.get(metadata_url)
        assert meta_response.status_code == 200
        data = meta_response.json()
        assert data.get("authorization_servers") == [f"{server_config.base_url}/"]


async def test_mcp_tool_metrics_exported_over_streamable_http(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    notebook_file_id: int,
) -> None:
    """Verify standalone MCP server tool calls record Prometheus metrics visible on `/metrics`."""
    token = auth_headers["x-access-token"]
    headers = {"Authorization": f"Bearer {token}"}

    before_list_ok = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "list_notebooks", "status": "success"},
        )
        or 0.0
    )
    before_transcript_fail = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "get_notebook_transcript", "status": "failure"},
        )
        or 0.0
    )
    before_transcript_dur = (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": "get_notebook_transcript"},
        )
        or 0.0
    )

    async with mcp_session(mcp_url, headers) as session:
        await session.call_tool(
            "list_notebooks",
            arguments={"name_filter": "test_notes"},
            meta={"token": token},
        )
        err_call = await session.call_tool(
            "get_notebook_transcript",
            arguments={"file_id": "999999"},
            meta={"token": token},
        )
        assert err_call.content
        err_content = err_call.content[0]
        assert isinstance(err_content, TextContent)
        assert json.loads(err_content.text) == {
            "success": False,
            "errorCode": "404",
            "errorMsg": "No transcript found for notebook 999999.",
        }

    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "list_notebooks", "status": "success"},
        )
        == before_list_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": "get_notebook_transcript", "status": "failure"},
        )
        == before_transcript_fail + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": "get_notebook_transcript"},
        )
        == before_transcript_dur + 1.0
    )

    metrics_resp = await client.get("/metrics")
    assert metrics_resp.status == 200
    metrics_body = await metrics_resp.text()
    assert "supernote_mcp_tool_calls_total" in metrics_body
    assert "supernote_mcp_tool_duration_seconds_bucket" in metrics_body
