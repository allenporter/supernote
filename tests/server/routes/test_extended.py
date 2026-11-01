import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.exceptions import ApiException
from supernote.client.extended import ExtendedClient
from supernote.client.summary import SummaryClient
from supernote.models.base import ProcessingStatus
from supernote.models.extended import PageTranscriptVO
from supernote.models.summary import AddSummaryDTO
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SupernoteError
from supernote.server.services.user import UserService


@pytest.fixture
def extended_client(authenticated_client: Client) -> ExtendedClient:
    """Fixture for ExtendedClient."""
    return ExtendedClient(authenticated_client)


@pytest.fixture
def server_config(server_config: ServerConfig) -> ServerConfig:
    """Configure fake AI models for extended route tests."""
    server_config.ai = AiConfig(
        ocr=ModelConfig(provider="fake", model="fake-ocr-v1"),
        summary=ModelConfig(provider="fake", model="fake-summary-v1"),
        embedding=ModelConfig(provider="fake", model="fake-embedding-v1"),
    )
    return server_config


async def test_extended_search(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
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
                page_id="P20231027120000abc",
                text_content="The quick brown fox jumps over the lazy dog.",
                # Mock embedding [1, 0, 0] for simplicity in SQL
                embedding="[1.0, 0.0, 0.0]",
                embedding_model="fake-embedding-v1",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="p1",
                text_content="Second page content.",
                embedding="[0.0, 1.0, 0.0]",
                embedding_model="fake-embedding-v1",
            )
        )
        await session.commit()

    resp = await extended_client.get_transcript(file_id=file_id)
    assert resp.success
    assert resp.pages == [
        PageTranscriptVO(
            page_index=0,
            page_id="P20231027120000abc",
            text="The quick brown fox jumps over the lazy dog.",
            date="2023-10-27",
        ),
        PageTranscriptVO(
            page_index=1,
            page_id="p1",
            text="Second page content.",
            date=None,
        ),
    ]

    range_resp = await extended_client.get_transcript(
        file_id=file_id, start_index=1, end_index=1
    )
    assert range_resp.success
    assert range_resp.pages == [
        PageTranscriptVO(
            page_index=1,
            page_id="p1",
            text="Second page content.",
            date=None,
        ),
    ]


async def test_extended_search_with_mock(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    client: Any,  # TestClient from aiohttp
    test_user_id: int,
) -> None:
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
                embedding_model="fake-embedding-v1",
            )
        )
        await session.commit()

    # The Gemini service is mocked globally by mock_gemini_service
    resp = await extended_client.search(query="fox")

    assert resp.success
    assert len(resp.results) > 0
    assert resp.results[0].file_id == file_id
    assert "quick brown fox" in resp.results[0].text_preview


async def test_extended_search_raw_camelcase_json_contract(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify /api/extended/search honors camelCase topN and returns camelCase result keys."""
    assert client.app is not None
    query_vec = await client.app["embedding_model"].embed(
        "deep-dive", EmbeddingTaskType.RETRIEVAL_QUERY
    )
    opposite_vec = [-v for v in query_vec]

    file_id = 102
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                file_name="Architecture.note",
                directory_id=0,
            )
        )
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="P20250115100000abc",
                    text_content="Page one overview.",
                    embedding=json.dumps(opposite_vec),
                    embedding_model="fake-embedding-v1",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=2,
                    page_id="P20250116100000def",
                    text_content="Page three deep-dive.",
                    embedding=json.dumps(query_vec),
                    embedding_model="fake-embedding-v1",
                ),
            ]
        )
        await session.commit()

    raw_resp = await extended_client._client.post(
        "/api/extended/search",
        json={"query": "deep-dive", "topN": 1},
    )
    assert raw_resp.status == 200
    payload = await raw_resp.json()
    assert payload["success"] is True
    assert len(payload["results"]) == 1
    hit = payload["results"][0]
    assert hit["fileId"] == file_id
    assert hit["fileName"] == "Architecture.note"
    assert hit["pageIndex"] == 2
    assert hit["pageId"] == "P20250116100000def"
    assert hit["textPreview"] == "Page three deep-dive."
    assert hit["date"] == "2025-01-16"
    assert isinstance(hit["score"], float)


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
    test_user_id: int,
) -> None:
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=1,
                user_id=test_user_id,
                file_name="Note1.note",
                directory_id=0,
            )
        )
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


async def test_handle_list_system_tasks_excludes_other_users_tasks(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify GET /api/extended/system/tasks only returns tasks for the authenticated user's files."""
    other_user_id = test_user_id + 999
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=1,
                user_id=test_user_id,
                file_name="OwnNote.note",
                directory_id=0,
            )
        )
        session.add(
            UserFileDO(
                id=2,
                user_id=other_user_id,
                file_name="OtherUserSecret.note",
                directory_id=0,
            )
        )
        session.add(
            SystemTaskDO(file_id=1, task_type="PNG", key="page_0", status="COMPLETED")
        )
        session.add(
            SystemTaskDO(
                file_id=2,
                task_type="OCR",
                key="page_0",
                status="FAILED",
                last_error="secret error",
            )
        )
        await session.commit()

    res = await extended_client.list_system_tasks()
    assert res.success
    returned_file_ids = {t.file_id for t in res.tasks}
    assert returned_file_ids == {1}


async def test_file_processing_status(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/file/processing/status",
            json={"invalid": "payload"},
        )

    async with session_manager.session() as session:
        for fid in (10, 20, 30, 40):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=test_user_id,
                    file_name=f"Note{fid}.note",
                    directory_id=0,
                )
            )
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


async def test_file_processing_status_excludes_other_users_files(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/file/processing/status does not leak task status for another user's file."""
    other_user_id = test_user_id + 999
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=77,
                user_id=other_user_id,
                file_name="OtherUser.note",
                directory_id=0,
            )
        )
        session.add(
            SystemTaskDO(file_id=77, task_type="PNG", key="p0", status="FAILED")
        )
        await session.commit()

    res = await extended_client.get_processing_status(file_ids=[77])
    assert res.success
    assert res.status_map["77"] == ProcessingStatus.NONE


async def test_extended_search_invalid_dto_and_errors(
    client: TestClient,
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/search",
            json={"invalid": "data"},
        )

    # User not found
    with (
        patch.object(user_service, "get_user_id", return_value=None),
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
    client: TestClient,
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    # Invalid DTO
    with pytest.raises(ApiException):
        await extended_client._client.post(
            "/api/extended/transcript",
            json={"invalid": "payload"},
        )

    # User not found
    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)

    # Transcript exception
    with (
        patch.object(
            client.app["search_service"],
            "get_page_transcripts",
            side_effect=Exception("Transcript crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)


async def test_extended_ai_status(extended_client: ExtendedClient) -> None:
    resp = await extended_client._client.get("/api/extended/ai/status")
    data = await resp.json()
    assert data == {
        "success": True,
        "hasApiKey": True,
        "ocrEnabled": True,
        "vectorSearchEnabled": True,
        "model": "fake-ocr-v1",
    }


async def test_extended_note_cover_converts_only_first_page(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    blob_storage = client.app["blob_storage"]
    conversion_service = client.app["conversion_service"]
    file_id = 9101
    storage_key = "cover_test_9101.note"
    multipage_note = Path("tests/testdata/mmujynya/stroller.note")

    await blob_storage.put(USER_DATA_BUCKET, storage_key, multipage_note.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="CoverOnly.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_cover_9101",
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/extended/file/note/cover",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["url"] is not None
    assert f"/api/oss/png/{file_id}/0?" in data["url"]

    # Page 1 was NOT eagerly converted
    assert (
        await conversion_service.get_note_png_page("test@example.com", file_id, 1)
        is None
    )

    # Signed URL downloads valid PNG bytes
    rel_url = "/" + data["url"].split("/", 3)[3]
    png_resp = await client.get(rel_url)
    assert png_resp.status == 200
    png_bytes = await png_resp.read()
    assert png_bytes.startswith(b"\x89PNG")

    # When web_notebook_preview is disabled, cover endpoint returns url=None
    client.app["config"].web_notebook_preview = False
    disabled_resp = await client.post(
        "/api/extended/file/note/cover",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert disabled_resp.status == 200
    disabled_data = await disabled_resp.json()
    assert disabled_data["success"] is True
    assert disabled_data["url"] is None
