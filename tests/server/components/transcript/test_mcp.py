"""MCP protocol tests for `supernote.server.components.transcript.mcp`."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from supernote.models.user import UserRegisterDTO
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
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
async def seeded_transcript_notebook_id(
    test_user_id: int,
    session_manager: DatabaseSessionManager,
) -> int:
    """Seed an active `.note` file with two transcribed pages."""
    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            directory_id=0,
            file_name="journal.note",
            storage_key="journal_key",
        )
        db.add(file_do)
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=file_do.id,
                    page_index=0,
                    page_id="P20260115090000a",
                    text_content="First page notes.",
                ),
                NotePageContentDO(
                    file_id=file_do.id,
                    page_index=1,
                    page_id="P20260116090000b",
                    text_content="Second page notes.",
                ),
            ]
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


async def test_transcript_mcp_get_notebook_transcript_over_protocol(
    mcp_url: str,
    auth_headers: dict[str, str],
    seeded_transcript_notebook_id: int,
) -> None:
    """Verify `get_notebook_transcript` supports full and page-sliced reads over MCP."""
    before_ok = _call_count("get_notebook_transcript", "success")
    before_dur = _duration_count("get_notebook_transcript")

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert "get_notebook_transcript" in {t.name for t in tools.tools}

        full = await call_mcp_tool(
            session,
            "get_notebook_transcript",
            {"file_id": str(seeded_transcript_notebook_id)},
        )
        sliced = await call_mcp_tool(
            session,
            "get_notebook_transcript",
            {
                "file_id": str(seeded_transcript_notebook_id),
                "start_index": 1,
                "end_index": 1,
            },
        )

    assert full["success"] is True
    assert "First page notes." in full["transcript"]
    assert "Second page notes." in full["transcript"]
    assert "--- Page 1 ---" in full["transcript"]
    assert "Notebook Filename: journal.note" in full["transcript"]
    assert "Page ID: P20260115090000a" in full["transcript"]
    assert "Page Date (Inferred): 2026-01-15" in full["transcript"]
    assert "Page Date (Inferred): 2026-01-16" in full["transcript"]

    assert sliced["success"] is True
    assert "Second page notes." in sliced["transcript"]
    assert "First page notes." not in sliced["transcript"]
    assert "--- Page 2 ---" in sliced["transcript"]
    assert "Page ID: P20260116090000b" in sliced["transcript"]

    assert _call_count("get_notebook_transcript", "success") == before_ok + 2.0
    assert _duration_count("get_notebook_transcript") == before_dur + 2.0


async def test_transcript_mcp_includes_verified_page_keywords(
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify MCP transcript reads render verified page keywords matching (page_id, content_hash)."""
    async with session_manager.session() as db:
        arch = UserFileDO(
            user_id=test_user_id,
            file_name="Architecture.note",
            directory_id=0,
            is_active="Y",
            storage_key="arch_mcp_key",
        )
        db.add(arch)
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=arch.id,
                    page_index=0,
                    page_id="P20260301090000a",
                    content_hash="h_arch",
                    text_content="Discussed schema design.",
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=arch.id,
                    page_index=0,
                    page_id="P20260301090000a",
                    content_hash="h_arch",
                    keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "SQLite"}]',
                ),
            ]
        )
        await db.commit()
        arch_id = str(arch.id)

    async with mcp_session(mcp_url, auth_headers) as session:
        arch_resp = await call_mcp_tool(
            session, "get_notebook_transcript", {"file_id": arch_id}
        )
        assert arch_resp["success"] is True
        assert "Page Keywords: SQLite" in arch_resp["transcript"]


async def test_transcript_mcp_enforces_access_and_active_checks(
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify MCP transcript reads return 404 for other users', soft-deleted, and unprocessed notebooks."""
    other_account = await user_service.register(
        UserRegisterDTO(email="other_transcript_mcp@example.com", password="a" * 32)
    )
    async with session_manager.session() as db:
        other_user = UserFileDO(
            user_id=other_account.id,
            file_name="Secret.note",
            directory_id=0,
            is_active="Y",
            storage_key="secret_mcp_key",
        )
        deleted = UserFileDO(
            user_id=test_user_id,
            file_name="Deleted.note",
            directory_id=0,
            is_active="N",
            storage_key="deleted_mcp_key",
        )
        unprocessed = UserFileDO(
            user_id=test_user_id,
            file_name="Pending.note",
            directory_id=0,
            is_active="Y",
            storage_key="pending_mcp_key",
        )
        db.add_all([other_user, deleted, unprocessed])
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=other_user.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Other user secret",
                ),
                NotePageContentDO(
                    file_id=deleted.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Deleted content",
                ),
                NotePageContentDO(
                    file_id=unprocessed.id,
                    page_index=0,
                    page_id="p0",
                    text_content=None,
                ),
            ]
        )
        await db.commit()
        inaccessible_ids = [str(other_user.id), str(deleted.id), str(unprocessed.id)]

    async with mcp_session(mcp_url, auth_headers) as session:
        for file_id in inaccessible_ids:
            resp = await call_mcp_tool(
                session, "get_notebook_transcript", {"file_id": file_id}
            )
            assert resp["success"] is False
            assert resp["errorCode"] == "404"


async def test_transcript_mcp_invalid_id_and_not_found_over_protocol(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Verify invalid file_id (400) and missing notebook (404) over MCP Streamable HTTP."""
    before_fail = _call_count("get_notebook_transcript", "failure")

    async with mcp_session(mcp_url, auth_headers) as session:
        bad_id = await call_mcp_tool(
            session,
            "get_notebook_transcript",
            {"file_id": "abc"},
        )
        not_found = await call_mcp_tool(
            session,
            "get_notebook_transcript",
            {"file_id": "999999"},
        )

    assert bad_id == {
        "success": False,
        "errorCode": "400",
        "errorMsg": "Invalid file_id 'abc': must be a numeric ID string.",
    }
    assert not_found == {
        "success": False,
        "errorCode": "404",
        "errorMsg": "No transcript found for notebook 999999.",
    }
    assert _call_count("get_notebook_transcript", "failure") == before_fail + 2.0


async def test_transcript_mcp_backend_error_records_failure_metric(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Verify unhandled TranscriptService errors return MCP tool error and record failure."""
    before_fail = _call_count("get_notebook_transcript", "failure")
    before_dur = _duration_count("get_notebook_transcript")

    with patch.object(
        client.app[TRANSCRIPT_SERVICE_KEY],
        "get_transcript",
        side_effect=RuntimeError("db error"),
    ):
        async with mcp_session(mcp_url, auth_headers) as session:
            result = await session.call_tool(
                "get_notebook_transcript",
                arguments={"file_id": "101"},
            )

    assert result.is_error is True
    assert _call_count("get_notebook_transcript", "failure") == before_fail + 1.0
    assert _duration_count("get_notebook_transcript") == before_dur + 1.0
