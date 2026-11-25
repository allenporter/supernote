"""MCP protocol tests for `supernote.server.components.search.mcp`."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from supernote.models.user import UserRegisterDTO
from supernote.server.components.search import SEARCH_SERVICE_KEY
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.user import UserService
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


@pytest.fixture
def server_config(server_config: ServerConfig) -> ServerConfig:
    """Configure the fake embedding provider through the `ai` + `fake_ai` components."""
    server_config.ai = AiConfig(
        embedding=ModelConfig(provider="fake", model="fake-embedding-v1"),
    )
    return server_config


@pytest.fixture
async def seeded_notebook_id(
    test_user_id: int,
    session_manager: DatabaseSessionManager,
) -> int:
    """Seed an active `.note` file and embedded page content for the test user."""
    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            directory_id=0,
            file_name="roadmap_notes.note",
            storage_key="roadmap_notes_key",
        )
        db.add(file_do)
        await db.flush()
        db.add(
            NotePageContentDO(
                file_id=file_do.id,
                page_index=0,
                page_id="P20260115090000a",
                text_content="Quarterly architecture milestones.",
                embedding=json.dumps([0.1] * 3),
                embedding_model="fake-embedding-v1",
            )
        )
        db.add(
            NotePageMetadataDO(
                user_id=test_user_id,
                file_id=file_do.id,
                page_index=1,
                page_id="P20260116090000b",
                keywords_json=json.dumps([{"KEYWORDPAGE": "2", "KEYWORD": "ks-tilt"}]),
            )
        )
        await db.commit()
        return int(file_do.id)


def _call_count(tool: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": tool, "status": status},
        )
        or 0.0
    )


def _duration_count(tool: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": tool},
        )
        or 0.0
    )


async def test_search_mcp_list_notebooks_over_protocol(
    mcp_url: str,
    auth_headers: dict[str, str],
    seeded_notebook_id: int,
) -> None:
    """Verify `list_notebooks` works over MCP Streamable HTTP and records metrics."""
    before_ok = _call_count("list_notebooks", "success")
    before_dur = _duration_count("list_notebooks")

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        assert {"list_notebooks", "search_notebook_chunks"} <= tool_names

        data = await call_mcp_tool(
            session,
            "list_notebooks",
            {"name_filter": "roadmap", "limit": 10},
        )

    assert data["success"] is True
    assert len(data["notebooks"]) == 1
    assert data["notebooks"][0]["fileId"] == str(seeded_notebook_id)
    assert data["notebooks"][0]["fileName"] == "roadmap_notes.note"
    assert _call_count("list_notebooks", "success") == before_ok + 1.0
    assert _duration_count("list_notebooks") == before_dur + 1.0


async def test_search_mcp_list_notebooks_ordering_filtering_and_isolation(
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify `list_notebooks` orders by update_time desc, skips inactive/non-note/other-user files, and honors filters."""
    other_account = await user_service.register(
        UserRegisterDTO(email="other_search@example.com", password="a" * 32)
    )
    async with session_manager.session() as db:
        older = UserFileDO(
            user_id=test_user_id,
            file_name="Older.note",
            directory_id=0,
            is_folder="N",
            is_active="Y",
            create_time=1000,
            update_time=1500,
            storage_key="older_note_key",
        )
        newer = UserFileDO(
            user_id=test_user_id,
            file_name="Newer_Daily.note",
            directory_id=0,
            is_folder="N",
            is_active="Y",
            create_time=2000,
            update_time=3000,
            storage_key="newer_daily_key",
        )
        deleted = UserFileDO(
            user_id=test_user_id,
            file_name="Deleted.note",
            directory_id=0,
            is_folder="N",
            is_active="N",
            create_time=4000,
            update_time=5000,
            storage_key="deleted_note_key",
        )
        pdf = UserFileDO(
            user_id=test_user_id,
            file_name="Document.pdf",
            directory_id=0,
            is_folder="N",
            is_active="Y",
            create_time=4000,
            update_time=5000,
            storage_key="document_pdf_key",
        )
        other_user = UserFileDO(
            user_id=other_account.id,
            file_name="OtherUser.note",
            directory_id=0,
            is_folder="N",
            is_active="Y",
            create_time=4000,
            update_time=5000,
            storage_key="other_user_note_key",
        )
        db.add_all([older, newer, deleted, pdf, other_user])
        await db.commit()
        older_id, newer_id = str(older.id), str(newer.id)

    async with mcp_session(mcp_url, auth_headers) as session:
        all_resp = await call_mcp_tool(session, "list_notebooks", {})
        filtered = await call_mcp_tool(
            session, "list_notebooks", {"name_filter": "daily"}
        )
        limited = await call_mcp_tool(session, "list_notebooks", {"limit": 1})

    assert [n["fileId"] for n in all_resp["notebooks"]] == [newer_id, older_id]
    assert all_resp["notebooks"][0]["fileName"] == "Newer_Daily.note"
    assert all_resp["notebooks"][0]["createTime"] == 2000
    assert all_resp["notebooks"][0]["updateTime"] == 3000

    assert [n["fileId"] for n in filtered["notebooks"]] == [newer_id]
    assert [n["fileId"] for n in limited["notebooks"]] == [newer_id]


async def test_search_mcp_search_notebook_chunks_over_protocol(
    mcp_url: str,
    auth_headers: dict[str, str],
    seeded_notebook_id: int,
) -> None:
    """Verify `search_notebook_chunks` returns ranked hits over MCP Streamable HTTP."""
    before_ok = _call_count("search_notebook_chunks", "success")

    async with mcp_session(mcp_url, auth_headers) as session:
        data = await call_mcp_tool(
            session,
            "search_notebook_chunks",
            {
                "query": "architecture milestones",
                "top_n": 5,
                "name_filter": "roadmap",
                "date_after": "2026-01-01",
                "date_before": "2026-12-31",
            },
        )
        tag_data = await call_mcp_tool(
            session,
            "search_notebook_chunks",
            {"query": "#KS-Tilt", "top_n": 5, "date_after": "2026-01-16"},
        )

    assert data["success"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["fileId"] == str(seeded_notebook_id)
    assert data["results"][0]["fileName"] == "roadmap_notes.note"
    assert data["results"][0]["textPreview"] == "Quarterly architecture milestones."
    assert data["results"][0]["date"] == "2026-01-15"
    assert tag_data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "results": [
            {
                "fileId": str(seeded_notebook_id),
                "fileName": "roadmap_notes.note",
                "pageIndex": 1,
                "pageId": "P20260116090000b",
                "score": 1.0,
                "textPreview": "Keywords: #ks-tilt",
                "date": "2026-01-16",
            }
        ],
    }
    assert _call_count("search_notebook_chunks", "success") == before_ok + 2.0


async def test_search_mcp_backend_error_records_failure_metric(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Verify unhandled SearchService errors return MCP tool error and record failure metric."""
    before_fail = _call_count("search_notebook_chunks", "failure")
    before_dur = _duration_count("search_notebook_chunks")

    with patch.object(
        client.app[SEARCH_SERVICE_KEY],
        "search_chunks",
        side_effect=RuntimeError("backend down"),
    ):
        async with mcp_session(mcp_url, auth_headers) as session:
            result = await session.call_tool(
                "search_notebook_chunks",
                arguments={"query": "notes"},
            )

    assert result.is_error is True
    assert _call_count("search_notebook_chunks", "failure") == before_fail + 1.0
    assert _duration_count("search_notebook_chunks") == before_dur + 1.0
