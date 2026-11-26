import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from yarl import URL

from supernote.client.api import Supernote
from supernote.client.exceptions import ApiException
from supernote.client.extended import ExtendedClient
from supernote.client.schedule import ScheduleClient
from supernote.client.summary import SummaryClient
from supernote.models.base import ProcessingStatus
from supernote.models.extended import PageTranscriptVO
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.ai import EMBEDDING_MODEL_KEY
from supernote.server.components.note_metadata import NOTE_METADATA_SERVICE_KEY
from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.components.processor.page_hashing import PageHashingModule
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    NoteTitleDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import Event, NoteUpdatedEvent
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    FILE_SERVICE_KEY,
)
from supernote.server.services.user import UserService


@pytest.fixture
def ai_config() -> AiConfig:
    """Default AI configuration for extended route tests."""
    return AiConfig(
        ocr=ModelConfig(provider="fake_ai", model="fake-ocr-v1"),
        summary=ModelConfig(provider="fake_ai", model="fake-summary-v1"),
        embedding=ModelConfig(provider="fake_ai", model="fake-embedding-v1"),
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
            UserFileDO(
                id=2,
                user_id=test_user_id,
                file_name="RecycledNote.note",
                directory_id=0,
                is_active="N",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=1,
                page_index=3,
                page_id="P202611240001",
                content_hash="abc",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=1,
                task_type="OCR_EXTRACTION",
                key="page_P202611240001",
                status="COMPLETED",
                update_time=2000,
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=1,
                task_type="SUMMARY_GENERATION",
                key="global",
                status="FAILED",
                last_error="Gemini rate limit exceeded",
                update_time=1000,
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=2,
                task_type="OCR_EXTRACTION",
                key="page_0",
                status="FAILED",
                last_error="Soft-deleted file failure should not leak into active queue",
                update_time=3000,
            )
        )
        await session.commit()

    res = await extended_client.list_system_tasks()
    assert res.success
    assert len(res.tasks) == 2
    # FAILED task should be prioritized ahead of COMPLETED task even with older update_time
    assert res.tasks[0].status == "FAILED"
    assert res.tasks[0].file_name == "Note1.note"
    assert res.tasks[0].page_index is None
    assert res.tasks[1].status == "COMPLETED"
    assert res.tasks[1].file_name == "Note1.note"
    assert res.tasks[1].page_index == 3

    with (
        patch.object(
            client.app[PROCESSOR_SERVICE_KEY],
            "list_user_system_task_vos",
            side_effect=Exception("DB error"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_system_tasks()


async def test_handle_retry_system_tasks(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    other_user_id = test_user_id + 888
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=101,
                user_id=test_user_id,
                file_name="FailedOwn.note",
                directory_id=0,
            )
        )
        session.add(
            UserFileDO(
                id=102,
                user_id=other_user_id,
                file_name="FailedOther.note",
                directory_id=0,
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=101,
                task_type="OCR_EXTRACTION",
                key="page_0",
                status="FAILED",
                last_error="timeout",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=101,
                task_type="PNG_CONVERSION",
                key="page_0",
                status="COMPLETED",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=101,
                task_type="HASHING",
                key="global",
                status="COMPLETED",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=101,
                task_type="SUMMARY_GENERATION",
                key="global",
                status="COMPLETED",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=other_user_id,
                file_id=102,
                task_type="OCR_EXTRACTION",
                key="page_0",
                status="FAILED",
                last_error="other user failure",
            )
        )
        await session.commit()

    processor_service = client.app[PROCESSOR_SERVICE_KEY]
    await processor_service.pause()
    published_ids: list[int] = []

    async def capture_updated(event: Event) -> None:
        if isinstance(event, NoteUpdatedEvent):
            published_ids.append(event.file_id)

    processor_service.event_bus.subscribe(
        NoteUpdatedEvent, capture_updated, inline=True
    )

    resp = await client.post(
        "/api/extended/system/tasks/retry",
        json={"fileId": "101"},
        headers=auth_headers,
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["retriedFileIds"] == ["101"]
    assert published_ids == [101]

    # Own FAILED task and downstream SUMMARY_GENERATION global checkpoint cleared
    # while HASHING, PNG_CONVERSION, and other user's FAILED task remain untouched
    own_tasks = await processor_service.list_system_tasks(user_id=test_user_id)
    assert {t.task_type for t in own_tasks} == {"HASHING", "PNG_CONVERSION"}
    other_tasks = await processor_service.list_system_tasks(user_id=other_user_id)
    assert len(other_tasks) == 1
    assert other_tasks[0].status == "FAILED"


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
            SystemTaskDO(
                user_id=test_user_id,
                file_id=1,
                task_type="PNG",
                key="page_0",
                status="COMPLETED",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=other_user_id,
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
            SystemTaskDO(
                user_id=test_user_id,
                file_id=10,
                task_type="PNG",
                key="p0",
                status="FAILED",
            )
        )
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=10,
                task_type="OCR",
                key="p0",
                status="COMPLETED",
            )
        )
        # File 20: PROCESSING task
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=20,
                task_type="PNG",
                key="p0",
                status="PROCESSING",
            )
        )
        # File 30: All COMPLETED
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=30,
                task_type="PNG",
                key="p0",
                status="COMPLETED",
            )
        )
        # File 40: PENDING task
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=40,
                task_type="PNG",
                key="p0",
                status="PENDING",
            )
        )
        # 64-bit Snowflake ID (> Number.MAX_SAFE_INTEGER in JS, sent as string)
        session.add(
            SystemTaskDO(
                user_id=test_user_id,
                file_id=snowflake_id,
                task_type="OCR",
                key="p0",
                status="PROCESSING",
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
            SystemTaskDO(
                user_id=other_user_id,
                file_id=77,
                task_type="PNG",
                key="p0",
                status="FAILED",
            )
        )
        await session.commit()

    res = await extended_client.get_processing_status(file_ids=[77])
    assert res.success
    assert res.status_map["77"] == ProcessingStatus.NONE


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
            summary=ModelConfig(provider="fake_ai", model="ollama-summary-v1"),
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
                user_id=test_user_id,
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


async def test_extended_api_keys_unauthorized(client: TestClient) -> None:
    """Test that all API keys endpoints return 401 without authentication."""
    get_resp = await client.get("/api/extended/keys")
    assert get_resp.status == 401

    post_resp = await client.post("/api/extended/keys", json={"name": "Test Key"})
    assert post_resp.status == 401

    del_resp = await client.delete("/api/extended/keys/key_123")
    assert del_resp.status == 401


async def test_extended_api_keys_crud_lifecycle(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
) -> None:
    """Test full CRUD lifecycle for static Bearer API keys via ExtendedClient and routes."""
    initial_list = await extended_client.list_api_keys()
    assert initial_list.success is True
    assert initial_list.keys == []

    bad_json = await client.post(
        "/api/extended/keys",
        data="invalid-json",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert bad_json.status == 400

    for invalid_name in ("   ", "x" * 101, "Bad\x1b[31mName"):
        with pytest.raises(ApiException):
            await extended_client.create_api_key(invalid_name)

    for bad_days in (0, -5, 3651):
        with pytest.raises(ApiException):
            await extended_client.create_api_key("Bad Expiry", expires_in_days=bad_days)

    bad_exp = await client.post(
        "/api/extended/keys",
        json={"name": "Bad Expiry", "expiresInDays": "not-an-int"},
        headers=auth_headers,
    )
    assert bad_exp.status == 400

    created_1 = await extended_client.create_api_key("Claude Desktop")
    assert created_1.success is True
    assert len(created_1.id) == 16
    assert created_1.name == "Claude Desktop"
    assert created_1.key.startswith("sn_")
    assert len(created_1.key) == 35
    assert created_1.created_at > 0
    assert created_1.expires_at is None

    listed_1 = await extended_client.list_api_keys()
    assert len(listed_1.keys) == 1
    assert listed_1.keys[0].id == created_1.id
    assert listed_1.keys[0].name == "Claude Desktop"
    assert listed_1.keys[0].key_prefix == f"{created_1.key[:11]}..."
    assert listed_1.keys[0].created_at == created_1.created_at
    assert listed_1.keys[0].last_used_at is None
    assert listed_1.keys[0].expires_at is None

    created_2 = await extended_client.create_api_key(
        "Obsidian Sync", expires_in_days=30
    )
    assert created_2.expires_at is not None
    assert created_2.expires_at > created_2.created_at

    listed_2 = await extended_client.list_api_keys()
    assert {k.id for k in listed_2.keys} == {created_1.id, created_2.id}

    del_res = await extended_client.delete_api_key(created_1.id)
    assert del_res.success is True

    with pytest.raises(ApiException):
        await extended_client.delete_api_key(created_1.id)

    with pytest.raises(ApiException):
        await extended_client.delete_api_key("unknown_key_999")

    listed_after = await extended_client.list_api_keys()
    assert [k.id for k in listed_after.keys] == [created_2.id]

    del2_res = await extended_client.delete_api_key(created_2.id)
    assert del2_res.success is True
    assert (await extended_client.list_api_keys()).keys == []


async def test_bearer_tokens_work_across_all_apis(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
) -> None:
    """Verify Supernote.from_token authenticates with static API keys and session tokens across APIs."""
    created = await extended_client.create_api_key("Universal Client")
    base_url = str(client.make_url(""))

    sn_api_key = Supernote.from_token(
        created.key, host=base_url, session=client.session
    )
    sn_session = Supernote.from_token(
        auth_headers["x-access-token"], host=base_url, session=client.session
    )

    for sn in (sn_api_key, sn_session):
        ai_status = await sn.extended.get_ai_status()
        assert ai_status.success is True

        cap = await sn.web.get_capacity_web()
        assert cap.success is True

        profile = await sn.web.query_user()
        assert profile.email == "test@example.com"

        groups = [g async for g in ScheduleClient(sn.client).list_groups()]
        assert isinstance(groups, list)

        tags = await SummaryClient(sn.client).query_tags()
        assert tags.success is True

    # Revoking the static API key immediately rejects Bearer requests across APIs
    await extended_client.delete_api_key(created.id)
    with pytest.raises(ApiException):
        await sn_api_key.web.get_capacity_web()


async def test_api_keys_denied_on_key_management_endpoints(
    client: TestClient,
    extended_client: ExtendedClient,
) -> None:
    """Verify static API keys cannot list, create, or delete API keys (no self-escalation)."""
    created = await extended_client.create_api_key("Restricted Agent")
    sn_api_key = Supernote.from_token(
        created.key, host=str(client.make_url("")), session=client.session
    )

    with pytest.raises(ApiException):
        await sn_api_key.extended.list_api_keys()

    with pytest.raises(ApiException):
        await sn_api_key.extended.create_api_key("Escalated Key")

    with pytest.raises(ApiException):
        await sn_api_key.extended.delete_api_key(created.id)

    # Also verify legacy x-access-token header with static API key is rejected
    legacy_headers = {"x-access-token": created.key}
    assert (
        await client.get("/api/extended/keys", headers=legacy_headers)
    ).status == 403


async def test_extended_oauth_grants_unauthorized(client: TestClient) -> None:
    """Test that OAuth grant endpoints return 401 without authentication."""
    assert (await client.get("/api/extended/oauth/grants")).status == 401
    assert (await client.delete("/api/extended/oauth/grants/g1")).status == 401


async def test_api_keys_denied_on_oauth_grant_endpoints(
    client: TestClient,
    extended_client: ExtendedClient,
) -> None:
    """Verify static API keys cannot list or revoke OAuth client grants."""
    created = await extended_client.create_api_key("Restricted Agent")
    sn_api_key = Supernote.from_token(
        created.key, host=str(client.make_url("")), session=client.session
    )

    with pytest.raises(ApiException):
        await sn_api_key.extended.list_oauth_grants()

    with pytest.raises(ApiException):
        await sn_api_key.extended.revoke_oauth_grant("g1")


async def test_extended_oauth_grants_empty_for_new_user(
    extended_client: ExtendedClient,
) -> None:
    """Test that a user with no authorized clients gets an empty grant list."""
    listed = await extended_client.list_oauth_grants()
    assert listed.success is True
    assert listed.grants == []


async def test_extended_note_metadata_returns_notebook_and_pages(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/file/note/metadata returns combined notebook and per-page metadata."""
    assert client.app is not None
    blob_storage = client.app[BLOB_STORAGE_KEY]
    file_service = client.app[FILE_SERVICE_KEY]
    file_id = 772252421643567500
    storage_key = "meta_route_772252421643567500.note"
    note_path = Path("tests/testdata/mmujynya/stroller.note")

    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="MetadataRoute.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_meta_route",
            )
        )
        await session.commit()

    hashing = PageHashingModule(file_service=file_service)
    assert await hashing.run(file_id, session_manager, user_id=test_user_id) is True

    meta_vo = await extended_client.get_note_metadata(file_id=file_id)
    assert meta_vo.success is True
    assert meta_vo.file_id == file_id
    assert meta_vo.equipment == "N6"
    assert meta_vo.total_pages == 2
    assert meta_vo.keywords == {
        "ks-tilt": [0, 1],
        "ks-trapezoid": [0, 1],
        "ks-shapes": [0, 1],
    }
    assert len(meta_vo.pages) == 2
    assert meta_vo.pages[0].page_index == 0
    assert meta_vo.pages[0].style == "white"
    assert meta_vo.pages[0].is_blank is False
    assert meta_vo.pages[0].has_five_star is False
    assert meta_vo.pages[1].keywords == ["ks-tilt", "ks-trapezoid", "ks-shapes"]

    raw_resp = await client.post(
        "/api/extended/file/note/metadata",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert raw_resp.status == 200
    raw_json = await raw_resp.json()
    assert raw_json["fileId"] == str(file_id)
    assert raw_json["totalPages"] == 2
    assert len(raw_json["pages"]) == 2


async def test_extended_note_metadata_returns_titles_in_reading_order(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    blob_storage = client.app[BLOB_STORAGE_KEY]
    file_service = client.app[FILE_SERVICE_KEY]
    file_id = 772252421643567501
    storage_key = "meta_titles_772252421643567501.note"
    note_path = Path(
        "tests/testdata/philips/heading-n5-20260016-backgrounds-marker.note"
    )

    await blob_storage.put(USER_DATA_BUCKET, storage_key, note_path.read_bytes())
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name="Headings.note",
                is_folder="N",
                storage_key=storage_key,
                md5="md5_meta_titles",
            )
        )
        await session.commit()

    hashing = PageHashingModule(file_service=file_service)
    assert await hashing.run(file_id, session_manager, user_id=test_user_id) is True
    async with session_manager.session() as session:
        first = await session.get(NoteTitleDO, (test_user_id, file_id, 0))
        assert first is not None
        first.text_content = "Black"
        await session.commit()

    resp = await client.post(
        "/api/extended/file/note/metadata",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert resp.status == 200
    titles = (await resp.json())["titles"]
    image_urls = [URL(t.pop("imageUrl")) for t in titles]
    md5s = [
        "4f60eac0ba701b4983269a55649430ad",
        "b094a9f71c442cf2a0544d737603b0dc",
        "f14caee340e90ceab17cad156682ca9c",
        "63bcfe0053116378ededa5038ba7e389",
    ]
    assert [(u.is_absolute(), u.path) for u in image_urls] == [
        (True, f"/api/oss/title/{file_id}/{md5}") for md5 in md5s
    ]
    assert all(u.query for u in image_urls)
    assert titles == [
        {
            "pageIndex": 1,
            "level": 1,
            "text": "Black",
            "style": "1000254",
            "bitmapMd5": "4f60eac0ba701b4983269a55649430ad",
            "rect": [500, 329, 356, 148],
        },
        {
            "pageIndex": 1,
            "level": 2,
            "text": None,
            "style": "1157254",
            "bitmapMd5": "b094a9f71c442cf2a0544d737603b0dc",
            "rect": [480, 691, 582, 178],
        },
        {
            "pageIndex": 1,
            "level": 3,
            "text": None,
            "style": "1201000",
            "bitmapMd5": "f14caee340e90ceab17cad156682ca9c",
            "rect": [490, 1016, 284, 125],
        },
        {
            "pageIndex": 1,
            "level": 4,
            "text": None,
            "style": "1000000",
            "bitmapMd5": "63bcfe0053116378ededa5038ba7e389",
            "rect": [508, 1295, 290, 118],
        },
    ]


async def test_extended_note_metadata_titles_empty_until_rehashed(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Notes hashed before titles were persisted report no titles until re-hashed."""
    file_id = 9212
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="PreV3.note",
                    is_folder="N",
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    file_type="note",
                    total_pages=1,
                    header_json="{}",
                    footer_json=json.dumps(
                        {
                            "TITLE_00010010": "100",
                            "__titles__": [{"TITLESTYLE": "1000254"}],
                        }
                    ),
                ),
            ]
        )
        await session.commit()

    meta_vo = await extended_client.get_note_metadata(file_id=file_id)
    assert meta_vo.titles == []


async def test_extended_note_metadata_not_found_for_unhashed_or_other_user_file(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/file/note/metadata returns 404 before hashing or for another user's file."""
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=9201,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Unhashed.note",
                    is_folder="N",
                ),
                UserFileDO(
                    id=9202,
                    user_id=test_user_id + 999,
                    directory_id=0,
                    file_name="OtherUser.note",
                    is_folder="N",
                ),
            ]
        )
        await session.commit()

    with pytest.raises(ApiException, match="404"):
        await extended_client.get_note_metadata(file_id=9201)

    with pytest.raises(ApiException, match="404"):
        await extended_client.get_note_metadata(file_id=9202)


async def test_extended_note_metadata_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    """Verify POST /api/extended/file/note/metadata handles invalid payloads, missing user, and service errors."""
    assert client.app is not None
    bad_resp = await client.post(
        "/api/extended/file/note/metadata",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(ApiException, match="404"),
    ):
        await extended_client.get_note_metadata(file_id=101)

    with (
        patch.object(
            client.app[NOTE_METADATA_SERVICE_KEY],
            "get_note_metadata",
            side_effect=RuntimeError("metadata boom"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_note_metadata(file_id=101)


async def test_extended_note_metadata_corrupt_header_raises_server_error(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify corrupt NoteMetadataDO.header_json raises a 500 error rather than returning 404."""
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=9203,
                user_id=test_user_id,
                directory_id=0,
                file_name="Corrupt.note",
                is_folder="N",
            )
        )
        session.add(
            NoteMetadataDO(
                user_id=test_user_id,
                file_id=9203,
                header_json="not-valid-json",
                footer_json="{}",
            )
        )
        await session.commit()

    with pytest.raises(ApiException, match="500"):
        await extended_client.get_note_metadata(file_id=9203)


async def test_extended_note_metadata_resolves_links(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify outgoing links resolve target file/page indices."""
    src_file_id = 9210
    dst_file_id = 9211
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=src_file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Source.note",
                    is_folder="N",
                ),
                UserFileDO(
                    id=dst_file_id,
                    user_id=test_user_id,
                    directory_id=0,
                    file_name="Target.note",
                    is_folder="N",
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=dst_file_id,
                    native_file_id="F_DST",
                    file_type="note",
                    signature="SN_FILE_VER_20230015",
                    total_pages=2,
                    header_json=json.dumps({"FILE_ID": "F_DST"}),
                    footer_json=json.dumps({}),
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=dst_file_id,
                    page_index=1,
                    page_id="P_DST_1",
                    has_ink=True,
                    has_drawables=True,
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=src_file_id,
                    native_file_id="F_SRC",
                    file_type="note",
                    signature="SN_FILE_VER_20230015",
                    total_pages=2,
                    header_json=json.dumps(
                        {"FILE_ID": "F_SRC", "APPLY_EQUIPMENT": "N5"}
                    ),
                    footer_json=json.dumps(
                        {
                            "LINKO_00010010001000100010": "300",
                            "LINKO_00020010001000100010": "400",
                            "LINKI_00010010001000100010": "500",
                            "__links__": [
                                {
                                    "LINKTYPE": "0",
                                    "LINKINOUT": "0",
                                    "LINKFILEID": "F_SRC",
                                    "PAGEID": "P_SRC_1",
                                },
                                {
                                    "LINKTYPE": "0",
                                    "LINKINOUT": "0",
                                    "LINKFILEID": "F_DST",
                                    "PAGEID": "P_DST_1",
                                },
                                {
                                    "LINKTYPE": "0",
                                    "LINKINOUT": "1",
                                    "LINKFILEID": "F_DST",
                                    "PAGEID": "P_SRC_0",
                                },
                            ],
                        }
                    ),
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=src_file_id,
                    page_index=0,
                    page_id="P_SRC_0",
                    page_style="style_h_8mm_ruled_line_a5x2",
                    has_ink=False,
                    has_drawables=False,
                    page_json=json.dumps({"FIVESTAR": "10,20,30,40"}),
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=src_file_id,
                    page_index=1,
                    page_id="P_SRC_1",
                    page_style="user_Daily",
                    has_ink=True,
                    has_drawables=True,
                    page_json=json.dumps({}),
                ),
            ]
        )
        await session.commit()

    meta_vo = await extended_client.get_note_metadata(file_id=src_file_id)
    assert [lk.to_dict() for lk in meta_vo.links] == [
        {
            "pageIndex": 0,
            "linkType": "page",
            "target": None,
            "targetFileId": None,
            "targetPageIndex": 1,
        },
        {
            "pageIndex": 1,
            "linkType": "page",
            "target": None,
            "targetFileId": str(dst_file_id),
            "targetPageIndex": 1,
        },
    ]
    assert meta_vo.pages[0].style == "8mm_ruled_line"
    assert meta_vo.pages[0].is_blank is True
    assert meta_vo.pages[0].has_five_star is True
    assert meta_vo.pages[1].style == "daily"
    assert meta_vo.pages[1].is_blank is False
    assert meta_vo.pages[1].has_five_star is False


async def test_extended_oauth_grants_lists_authorized_clients(
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    user_id = await user_service.get_user_id("test@example.com")
    await user_service.create_oauth_grant(
        user_id, "https://client.example.com/", ["supernote:all"]
    )
    [expected] = await user_service.list_oauth_grants(user_id)

    listed = await extended_client.list_oauth_grants()

    assert listed.grants == [expected]


async def test_extended_oauth_grants_disconnect(
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    user_id = await user_service.get_user_id("test@example.com")
    access, _ = await user_service.create_oauth_grant(user_id, "c", ["supernote:all"])
    [grant] = await user_service.list_oauth_grants(user_id)

    assert (await extended_client.revoke_oauth_grant(grant.id)).success is True
    assert await user_service.verify_token(access) is None


async def test_extended_oauth_grants_disconnect_unknown_is_404(
    extended_client: ExtendedClient,
) -> None:
    with pytest.raises(ApiException):
        await extended_client.revoke_oauth_grant("missing")


async def test_oauth_tokens_denied_on_oauth_grant_endpoints(
    client: TestClient,
    create_test_user: None,
    user_service: UserService,
) -> None:
    """An OAuth client cannot list or disconnect the user's other clients."""
    user_id = await user_service.get_user_id("test@example.com")
    access, _ = await user_service.create_oauth_grant(user_id, "c", ["supernote:all"])
    headers = {"Authorization": f"Bearer {access}"}

    assert (
        await client.get("/api/extended/oauth/grants", headers=headers)
    ).status == 403
    assert (
        await client.delete("/api/extended/oauth/grants/g1", headers=headers)
    ).status == 403
