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
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    CONFIG_KEY,
    CONVERSION_SERVICE_KEY,
    EMBEDDING_MODEL_KEY,
    EVENT_LOG_SERVICE_KEY,
    PROCESSOR_SERVICE_KEY,
    SEARCH_SERVICE_KEY,
    SUMMARY_SERVICE_KEY,
)
from supernote.server.services.user import UserService


@pytest.fixture
def extended_client(authenticated_client: Client) -> ExtendedClient:
    """Fixture for ExtendedClient."""
    return ExtendedClient(authenticated_client)


@pytest.fixture
def ai_config() -> AiConfig:
    """Default AI configuration for extended route tests."""
    return AiConfig(
        ocr=ModelConfig(provider="fake", model="fake-ocr-v1"),
        summary=ModelConfig(provider="fake", model="fake-summary-v1"),
        embedding=ModelConfig(provider="fake", model="fake-embedding-v1"),
    )


@pytest.fixture
def server_config(server_config: ServerConfig, ai_config: AiConfig) -> ServerConfig:
    """Configure fake AI models for extended route tests."""
    server_config.ai = ai_config
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
    embedding_model = client.app[EMBEDDING_MODEL_KEY]
    assert embedding_model is not None
    query_vec = await embedding_model.embed(
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

    search_resp = await extended_client.search(query="deep-dive", top_n=1)
    assert search_resp.success is True
    assert len(search_resp.results) == 1
    hit = search_resp.results[0]
    assert hit.file_id == file_id
    assert hit.file_name == "Architecture.note"
    assert hit.page_index == 2
    assert hit.page_id == "P20250116100000def"
    assert hit.text_preview == "Page three deep-dive."
    assert hit.date == "2025-01-16"
    assert isinstance(hit.score, float)


async def test_extended_transcript_not_found(
    extended_client: ExtendedClient,
) -> None:
    # Request transcript for non-existent file
    with pytest.raises(Exception, match="404"):  # The client raises for 404
        await extended_client.get_transcript(file_id=999)


async def test_extended_file_summary_list_invalid_json(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list",
        data="invalid json",
        headers=auth_headers,
    )
    assert resp.status == 400


async def test_extended_file_summary_list_invalid_dto(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list",
        json={},
        headers=auth_headers,
    )
    assert resp.status == 400


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
            client.app[SUMMARY_SERVICE_KEY],
            "list_summaries_for_file_internal",
            side_effect=SupernoteError("Custom summary error", status_code=400),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_summaries(file_id=101)

    with (
        patch.object(
            client.app[SUMMARY_SERVICE_KEY],
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
            client.app[PROCESSOR_SERVICE_KEY],
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
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    # Invalid DTO
    bad_resp = await client.post(
        "/api/extended/file/processing/status",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    snowflake_id = 772252421643567298
    async with session_manager.session() as session:
        for fid in (10, 20, 30, 40, 60, snowflake_id):
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
        # 64-bit Snowflake ID (> Number.MAX_SAFE_INTEGER in JS, sent as string)
        session.add(
            SystemTaskDO(
                file_id=snowflake_id, task_type="OCR", key="p0", status="PROCESSING"
            )
        )
        await session.commit()

    assert client.app is not None
    empty_res = await extended_client.get_processing_status(file_ids=[])
    assert empty_res.success
    assert empty_res.status_map == {}

    res = await extended_client.get_processing_status(file_ids=[10, 20, 30, 40, 50, 60])
    assert res.success
    assert res.status_map == {
        "10": ProcessingStatus.FAILED,
        "20": ProcessingStatus.PROCESSING,
        "30": ProcessingStatus.COMPLETED,
        "40": ProcessingStatus.PENDING,
        "50": ProcessingStatus.NONE,
        "60": ProcessingStatus.NONE,
    }

    raw_resp = await client.post(
        "/api/extended/file/processing/status",
        json={"fileIds": [str(snowflake_id)]},
        headers=auth_headers,
    )
    assert raw_resp.status == 200
    assert await raw_resp.json() == {
        "success": True,
        "statusMap": {str(snowflake_id): "PROCESSING"},
    }

    with (
        patch.object(
            client.app[PROCESSOR_SERVICE_KEY],
            "get_file_processing_statuses",
            side_effect=RuntimeError("Service fail"),
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
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    # Invalid DTO
    bad_resp = await client.post(
        "/api/extended/search",
        json={"invalid": "data"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    # User not found
    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")

    # Search exception
    with (
        patch.object(
            client.app[SEARCH_SERVICE_KEY],
            "search_chunks",
            side_effect=Exception("Search crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")


async def test_extended_transcript_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    # Invalid DTO
    bad_resp = await client.post(
        "/api/extended/transcript",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    # User not found
    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)

    # Transcript exception
    with (
        patch.object(
            client.app[SEARCH_SERVICE_KEY],
            "get_page_transcripts",
            side_effect=Exception("Transcript crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)


async def test_extended_ai_status(extended_client: ExtendedClient) -> None:
    status = await extended_client.get_ai_status()
    assert status.success is True
    assert status.has_api_key is True
    assert status.ocr_enabled is True
    assert status.ocr_model == "fake-ocr-v1"
    assert status.summary_enabled is True
    assert status.summary_model == "fake-summary-v1"
    assert status.vector_search_enabled is True
    assert status.embedding_model == "fake-embedding-v1"
    assert status.model == "fake-ocr-v1"


@pytest.mark.parametrize("ai_config", [AiConfig()])
async def test_extended_ai_status_disabled(extended_client: ExtendedClient) -> None:
    status = await extended_client.get_ai_status()
    assert status.success is True
    assert status.has_api_key is False
    assert status.ocr_enabled is False
    assert status.ocr_model is None
    assert status.summary_enabled is False
    assert status.summary_model is None
    assert status.vector_search_enabled is False
    assert status.embedding_model is None
    assert status.model is None


@pytest.mark.parametrize(
    "ai_config",
    [
        AiConfig(
            ocr=None,
            summary=ModelConfig(provider="fake", model="ollama-summary-v1"),
            embedding=None,
        )
    ],
)
async def test_extended_ai_status_mixed_keyless_provider(
    extended_client: ExtendedClient,
) -> None:
    status = await extended_client.get_ai_status()
    assert status.success is True
    assert status.has_api_key is True
    assert status.ocr_enabled is False
    assert status.ocr_model is None
    assert status.summary_enabled is True
    assert status.summary_model == "ollama-summary-v1"
    assert status.vector_search_enabled is False
    assert status.embedding_model is None
    assert status.model == "ollama-summary-v1"


async def test_extended_note_cover_converts_only_first_page(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    blob_storage = client.app[BLOB_STORAGE_KEY]
    conversion_service = client.app[CONVERSION_SERVICE_KEY]
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

    cover_vo = await extended_client.get_note_cover(file_id=file_id)
    assert cover_vo.success is True
    assert cover_vo.url is not None
    assert f"/api/oss/png/{file_id}/0?" in cover_vo.url

    # Also verify browser-style string fileId wire payload
    resp = await client.post(
        "/api/extended/file/note/cover",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert resp.status == 200

    # Page 1 was NOT eagerly converted
    assert (
        await conversion_service.get_note_png_page("test@example.com", file_id, 1)
        is None
    )

    # Signed URL downloads valid PNG bytes
    rel_url = "/" + cover_vo.url.split("/", 3)[3]
    png_resp = await client.get(rel_url)
    assert png_resp.status == 200
    png_bytes = await png_resp.read()
    assert png_bytes.startswith(b"\x89PNG")

    # When web_notebook_preview is disabled, cover endpoint returns url=None
    client.app[CONFIG_KEY].web_notebook_preview = False
    disabled_vo = await extended_client.get_note_cover(file_id=file_id)
    assert disabled_vo.success is True
    assert disabled_vo.url is None


async def test_extended_routes_64bit_string_ids(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify /api/extended/* preserves 63-bit Snowflake IDs as strings over JSON."""
    assert client.app is not None
    snowflake_file_id = 772252421643567298
    snowflake_task_id = 772252421643567999
    embedding_model = client.app[EMBEDDING_MODEL_KEY]
    assert embedding_model is not None
    query_vec = await embedding_model.embed(
        "snowflake-note", EmbeddingTaskType.RETRIEVAL_QUERY
    )

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=snowflake_file_id,
                user_id=test_user_id,
                file_name="Snowflake.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=snowflake_file_id,
                page_index=0,
                page_id="P20261109010101abc",
                text_content="snowflake-note precision check",
                embedding=json.dumps(query_vec),
                embedding_model="fake-embedding-v1",
            )
        )
        session.add(
            SystemTaskDO(
                id=snowflake_task_id,
                file_id=snowflake_file_id,
                task_type="OCR_EXTRACTION",
                key="P20261109010101abc",
                status=ProcessingStatus.COMPLETED.value,
                retry_count=0,
            )
        )
        await session.commit()

    search_http = await client.post(
        "/api/extended/search",
        json={"query": "snowflake-note", "topN": 1},
        headers=auth_headers,
    )
    assert (await search_http.json())["results"][0]["fileId"] == str(snowflake_file_id)

    tasks_http = await client.get("/api/extended/system/tasks", headers=auth_headers)
    task_json = (await tasks_http.json())["tasks"][0]
    assert task_json["id"] == str(snowflake_task_id)
    assert task_json["fileId"] == str(snowflake_file_id)

    status_http = await client.post(
        "/api/extended/file/processing/status",
        json={"fileIds": [str(snowflake_file_id)]},
        headers=auth_headers,
    )
    assert (await status_http.json())["statusMap"] == {
        str(snowflake_file_id): "COMPLETED"
    }

    transcript_http = await client.post(
        "/api/extended/transcript",
        json={"fileId": str(snowflake_file_id)},
        headers=auth_headers,
    )
    assert (await transcript_http.json())["pages"][0][
        "text"
    ] == "snowflake-note precision check"


async def test_extended_events_route_and_client(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify GET /api/extended/events cursor querying, filtering, and error responses."""
    assert client.app is not None
    event_log_service = client.app[EVENT_LOG_SERVICE_KEY]

    ev1 = await event_log_service.append(
        user_id=test_user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="772252421643567298",
        related_file_id=772252421643567298,
        actor="device:SN001",
        payload={"path": "/NOTE/todo.note"},
        timestamp_ms=1_700_000_001_000,
    )
    ev2 = await event_log_service.append(
        user_id=test_user_id,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="772252421643567298:0",
        related_file_id=772252421643567298,
        actor="system:processor",
        payload={"page_index": 0, "current_text": "buy milk"},
        timestamp_ms=1_700_000_002_000,
    )

    feed = await extended_client.list_events(cursor="0")
    assert [e.seq for e in feed.events] == [str(ev1.seq), str(ev2.seq)]
    assert feed.events[0].related_file_id == 772252421643567298
    assert feed.next_cursor == str(ev2.seq)
    assert feed.head_cursor == str(ev2.seq)
    assert feed.has_more is False

    # Filter by types, file_id, and exclude_actor
    filtered = await extended_client.list_events(
        cursor="0",
        types=["note.*"],
        file_id=772252421643567298,
        exclude_actor="device:SN001",
    )
    assert [e.seq for e in filtered.events] == [str(ev2.seq)]

    # Invalid fileId, limit, or cursor returns 400
    for bad_query in ("fileId=abc", "limit=abc", "limit=0", "cursor=bad"):
        resp = await client.get(
            f"/api/extended/events?{bad_query}", headers=auth_headers
        )
        assert resp.status == 400

    # User not found returns 404
    with patch.object(user_service, "get_user_id", return_value=None):
        not_found = await client.get("/api/extended/events", headers=auth_headers)
        assert not_found.status == 404

    # Unexpected exception returns 500
    with patch.object(
        event_log_service, "list_events", side_effect=RuntimeError("boom")
    ):
        err_resp = await client.get("/api/extended/events", headers=auth_headers)
        assert err_resp.status == 500
