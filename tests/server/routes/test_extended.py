from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.extended import ExtendedClient
from supernote.models.base import ProcessingStatus
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SupernoteError


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


async def test_extended_file_summary_list_invalid_json(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list",
        data="invalid json",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert data.get("error") == "Invalid JSON"


async def test_extended_file_summary_list_invalid_dto(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list", json={}, headers=auth_headers
    )
    assert resp.status == 400
    data = await resp.json()
    assert "Invalid Request" in data.get("error", "")


async def test_extended_file_summary_list_success(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list", json={"fileId": 101}, headers=auth_headers
    )
    assert resp.status == 200
    data = await resp.json()
    assert "summaryDOList" in data
    assert data.get("totalRecords") == 0


async def test_extended_file_summary_list_error(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    with patch.object(
        client.app["summary_service"],
        "list_summaries_for_file_internal",
        side_effect=SupernoteError("Custom summary error", status_code=400),
    ):
        resp = await client.post(
            "/api/extended/file/summary/list",
            json={"fileId": 101},
            headers=auth_headers,
        )
        assert resp.status == 400

    with patch.object(
        client.app["summary_service"],
        "list_summaries_for_file_internal",
        side_effect=ValueError("Uncaught error"),
    ):
        resp = await client.post(
            "/api/extended/file/summary/list",
            json={"fileId": 101},
            headers=auth_headers,
        )
        assert resp.status == 500


async def test_handle_list_system_tasks(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(file_id=1, task_type="PNG", key="page_0", status="COMPLETED")
        )
        await session.commit()

    resp = await client.get("/api/extended/system/tasks", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) >= 1

    with patch.object(
        client.app["processor_service"],
        "list_system_tasks",
        side_effect=Exception("DB error"),
    ):
        resp = await client.get("/api/extended/system/tasks", headers=auth_headers)
        assert resp.status == 500


async def test_file_processing_status(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
) -> None:
    # 1. Invalid DTO
    resp = await client.post(
        "/api/extended/file/processing/status",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert resp.status == 400

    # 2. Status map for various task states
    async with session_manager.session() as session:
        # File 10: FAILED task
        session.add(
            SystemTaskDO(file_id=10, task_type="PNG", key="p0", status="FAILED")
        )
        session.add(
            SystemTaskDO(file_id=10, task_type="OCR", key="p0", status="COMPLETED")
        )
        # File 20: PROCESSING task
        session.add(
            SystemTaskDO(file_id=20, task_type="PNG", key="p0", status="PROCESSING")
        )
        # File 30: All COMPLETED
        session.add(
            SystemTaskDO(file_id=30, task_type="PNG", key="p0", status="COMPLETED")
        )
        # File 40: PENDING task
        session.add(
            SystemTaskDO(file_id=40, task_type="PNG", key="p0", status="PENDING")
        )
        await session.commit()

    resp = await client.post(
        "/api/extended/file/processing/status",
        json={"fileIds": [10, 20, 30, 40, 50]},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    status_map = data["statusMap"]
    assert status_map["10"] == ProcessingStatus.FAILED
    assert status_map["20"] == ProcessingStatus.PROCESSING
    assert status_map["30"] == ProcessingStatus.COMPLETED
    assert status_map["40"] == ProcessingStatus.PENDING
    assert status_map["50"] == ProcessingStatus.NONE

    # 3. DB error
    with patch.object(
        client.app["session_manager"], "session", side_effect=Exception("Session fail")
    ):
        resp = await client.post(
            "/api/extended/file/processing/status",
            json={"fileIds": [10]},
            headers=auth_headers,
        )
        assert resp.status == 500


async def test_extended_search_invalid_dto_and_errors(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Invalid DTO
    resp = await client.post(
        "/api/extended/search", json={"invalid": "data"}, headers=auth_headers
    )
    assert resp.status == 400

    # User not found
    with patch.object(client.app["user_service"], "get_user_id", return_value=None):
        resp = await client.post(
            "/api/extended/search", json={"query": "test"}, headers=auth_headers
        )
        assert resp.status == 404

    # Search exception
    with patch.object(
        client.app["search_service"],
        "search_chunks",
        side_effect=Exception("Search crash"),
    ):
        resp = await client.post(
            "/api/extended/search", json={"query": "test"}, headers=auth_headers
        )
        assert resp.status == 500


async def test_extended_transcript_invalid_dto_and_errors(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Invalid DTO
    resp = await client.post(
        "/api/extended/transcript", json={"invalid": "payload"}, headers=auth_headers
    )
    assert resp.status == 400

    # User not found
    with patch.object(client.app["user_service"], "get_user_id", return_value=None):
        resp = await client.post(
            "/api/extended/transcript", json={"fileId": 101}, headers=auth_headers
        )
        assert resp.status == 404

    # Transcript exception
    with patch.object(
        client.app["search_service"],
        "get_transcript",
        side_effect=Exception("Transcript crash"),
    ):
        resp = await client.post(
            "/api/extended/transcript", json={"fileId": 101}, headers=auth_headers
        )
        assert resp.status == 500
