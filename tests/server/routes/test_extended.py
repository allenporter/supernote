from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.exceptions import ApiException
from supernote.client.extended import ExtendedClient
from supernote.client.summary import SummaryClient
from supernote.models.base import ProcessingStatus
from supernote.models.summary import AddSummaryDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SupernoteError


@pytest.fixture
def extended_client(authenticated_client: Client) -> ExtendedClient:
    """Fixture for ExtendedClient."""
    return ExtendedClient(authenticated_client)


@pytest.fixture
def mock_gemini_service() -> Generator[None]:
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
def patch_gemini_service(mock_gemini_service: Generator[None]) -> None:
    """Patch the Gemini service in the search service."""
    # This is handled by the mock_gemini_service fixture


async def test_extended_search(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    # 1. Seed some search data
    file_id = 101
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                file_name="SearchTest.note",
                directory_id=0,
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
    test_user_id: int,
) -> None:
    # 1. Seed data
    file_id = 101
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                file_name="Fox.note",
                directory_id=0,
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
    with pytest.raises(Exception, match="404"):  # The client raises for 404
        await extended_client.get_transcript(file_id=999)


async def test_extended_file_summary_list_invalid_json(
    extended_client: ExtendedClient,
) -> None:
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/file/summary/list",
            data="invalid json",
        )


async def test_extended_file_summary_list_invalid_dto(
    extended_client: ExtendedClient,
) -> None:
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/file/summary/list",
            json={},
        )


async def test_extended_file_summary_list_success(
    extended_client: ExtendedClient, summary_client: SummaryClient
) -> None:
    add_dto = AddSummaryDTO(
        parent_unique_identifier="group-1",
        unique_identifier="summary-101",
        content="Extended test content",
        file_id=101,
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.success

    res = await extended_client.list_summaries(file_id=101)
    assert len(res.summary_do_list) == 1
    assert res.summary_do_list[0].content == "Extended test content"
    assert res.total_records == 1


async def test_extended_file_summary_list_error(
    client: TestClient, extended_client: ExtendedClient
) -> None:
    with (
        patch.object(
            client.app["summary_service"],
            "list_summaries_for_file_internal",
            side_effect=SupernoteError("Custom summary error", status_code=400),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_summaries(file_id=101)

    with (
        patch.object(
            client.app["summary_service"],
            "list_summaries_for_file_internal",
            side_effect=ValueError("Uncaught error"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_summaries(file_id=101)


async def test_handle_list_system_tasks(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(file_id=1, task_type="PNG", key="page_0", status="COMPLETED")
        )
        await session.commit()

    res = await extended_client.list_system_tasks()
    assert res.success
    assert len(res.tasks) >= 1

    with (
        patch.object(
            client.app["processor_service"],
            "list_system_tasks",
            side_effect=Exception("DB error"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_system_tasks()


async def test_file_processing_status(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/file/processing/status",
            json={"invalid": "payload"},
        )

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

    res = await extended_client.get_processing_status(file_ids=[10, 20, 30, 40, 50])
    assert res.success
    status_map = res.status_map
    assert status_map["10"] == ProcessingStatus.FAILED
    assert status_map["20"] == ProcessingStatus.PROCESSING
    assert status_map["30"] == ProcessingStatus.COMPLETED
    assert status_map["40"] == ProcessingStatus.PENDING
    assert status_map["50"] == ProcessingStatus.NONE

    with (
        patch.object(
            client.app["session_manager"],
            "session",
            side_effect=Exception("Session fail"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_processing_status(file_ids=[10])


async def test_extended_search_invalid_dto_and_errors(
    client: TestClient, extended_client: ExtendedClient
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/search",
            json={"invalid": "data"},
        )

    # User not found
    with (
        patch.object(client.app["user_service"], "get_user_id", return_value=None),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")

    # Search exception
    with (
        patch.object(
            client.app["search_service"],
            "search_chunks",
            side_effect=Exception("Search crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")


async def test_extended_transcript_invalid_dto_and_errors(
    client: TestClient, extended_client: ExtendedClient
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/transcript",
            json={"invalid": "payload"},
        )

    # User not found
    with (
        patch.object(client.app["user_service"], "get_user_id", return_value=None),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)

    # Transcript exception
    with (
        patch.object(
            client.app["search_service"],
            "get_transcript",
            side_effect=Exception("Transcript crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)
