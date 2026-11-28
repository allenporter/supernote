"""MCP protocol tests for `supernote.server.components.files.mcp`."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import update

from supernote.models.base import ErrorCode
from supernote.server.components.files import mcp as files_mcp
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import VfsItemCreatedEvent
from supernote.server.keys import EVENT_BUS_KEY, FILE_SERVICE_KEY
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


async def test_files_mcp_upload_utf8_and_list_files(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
    test_users: list[str],
) -> None:
    """`upload_document` lands UTF-8 Markdown, emits `VfsItemCreatedEvent`, and appears in `list_files`."""
    file_service = client.app[FILE_SERVICE_KEY]
    event_bus = client.app[EVENT_BUS_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    created_events: list[VfsItemCreatedEvent] = []

    async def _on_created(ev: VfsItemCreatedEvent) -> None:
        created_events.append(ev)

    event_bus.subscribe(VfsItemCreatedEvent, _on_created)

    md_text = "# Research Brief\n\nSummary for e-ink reading.\n"
    expected_md5 = hashlib.md5(md_text.encode("utf-8")).hexdigest()

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert {"list_files", "upload_document"}.issubset({t.name for t in tools.tools})

        res = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "brief.md",
                "content": md_text,
                "reason": "deliver brief to inbox",
            },
        )
        await asyncio.sleep(0)

        assert res["success"] is True
        assert res["file"]["name"] == "brief.md"
        assert res["file"]["path"] == "/INBOX/brief.md"
        assert res["file"]["is_folder"] is False
        assert res["file"]["size"] == len(md_text.encode("utf-8"))
        assert res["file"]["md5"] == expected_md5

        assert len(created_events) == 1
        assert created_events[0].user_id == test_user_id
        assert created_events[0].name == "brief.md"

        flat = await call_mcp_tool(session, "list_files", {"path": "/INBOX"})
        assert flat["success"] is True
        assert [i["name"] for i in flat["items"]] == ["brief.md"]

        recursive = await call_mcp_tool(
            session, "list_files", {"path": "/", "recursive": True}
        )
        assert recursive["success"] is True
        assert any(i["path"] == "/INBOX/brief.md" for i in recursive["items"])


async def test_files_mcp_upload_base64_pdf(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """`upload_document` decodes base64 binary payloads accurately."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    pdf_bytes = b"%PDF-1.4\x00binary-body\xff"
    async with mcp_session(mcp_url, auth_headers) as session:
        res = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "paper.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
                "encoding": "base64",
            },
        )

    assert res["success"] is True
    assert res["file"]["path"] == "/INBOX/paper.pdf"
    assert res["file"]["size"] == len(pdf_bytes)
    assert res["file"]["md5"] == hashlib.md5(pdf_bytes).hexdigest()


@pytest.mark.parametrize(
    ("file_name", "content", "encoding"),
    [
        ("", "hello", "utf-8"),
        ("   ", "hello", "utf-8"),
        (" brief.md", "hello", "utf-8"),
        ("sub/brief.md", "hello", "utf-8"),
        ("..", "hello", "utf-8"),
        ("bad.pdf", "not-valid-base64!!!", "base64"),
        ("bad.txt", "hello", "latin-1"),
    ],
)
async def test_files_mcp_upload_rejects_invalid_inputs(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
    file_name: str,
    content: str,
    encoding: str,
) -> None:
    """Invalid filenames, malformed base64, and unsupported encodings return BAD_REQUEST."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with mcp_session(mcp_url, auth_headers) as session:
        res = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": file_name,
                "content": content,
                "encoding": encoding,
            },
        )

    assert res["success"] is False
    assert res["errorCode"] == ErrorCode.BAD_REQUEST


async def test_files_mcp_upload_enforces_size_limit(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """Payloads exceeding `MAX_INLINE_UPLOAD_BYTES` are rejected before commit."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    with patch.object(files_mcp, "MAX_INLINE_UPLOAD_BYTES", 8):
        async with mcp_session(mcp_url, auth_headers) as session:
            too_big_utf8 = await call_mcp_tool(
                session,
                "upload_document",
                {
                    "directory_path": "/INBOX",
                    "file_name": "too_big.txt",
                    "content": "0123456789",
                },
            )
            too_big_b64 = await call_mcp_tool(
                session,
                "upload_document",
                {
                    "directory_path": "/INBOX",
                    "file_name": "too_big.pdf",
                    "content": base64.b64encode(b"0123456789").decode("ascii"),
                    "encoding": "base64",
                },
            )

    assert too_big_utf8["success"] is False
    assert too_big_utf8["errorCode"] == ErrorCode.BAD_REQUEST
    assert too_big_b64["success"] is False
    assert too_big_b64["errorCode"] == ErrorCode.BAD_REQUEST


async def test_files_mcp_rejects_missing_dir_and_folder_collision(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """Missing folders return NOT_FOUND and uploading over an existing folder returns BAD_REQUEST."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with mcp_session(mcp_url, auth_headers) as session:
        missing_list = await call_mcp_tool(
            session, "list_files", {"path": "/NO_SUCH_DIR"}
        )
        missing_upload = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/NO_SUCH_DIR",
                "file_name": "paper.pdf",
                "content": "hello",
            },
        )
        folder_collision = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/",
                "file_name": "INBOX",
                "content": "hello",
            },
        )

    assert missing_list["success"] is False
    assert missing_list["errorCode"] == ErrorCode.NOT_FOUND
    assert missing_upload["success"] is False
    assert missing_upload["errorCode"] == ErrorCode.NOT_FOUND
    assert folder_collision["success"] is False
    assert folder_collision["errorCode"] == ErrorCode.BAD_REQUEST


async def test_files_mcp_upload_quota_exceeded(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Uploads exceeding user storage quota return QUOTA_EXCEEDED."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with session_manager.session() as db_session:
        await db_session.execute(
            update(UserDO).where(UserDO.id == test_user_id).values(total_capacity=5)
        )
        await db_session.commit()

    async with mcp_session(mcp_url, auth_headers) as session:
        over_quota = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "big.txt",
                "content": "0123456789",
            },
        )

    assert over_quota["success"] is False
    assert over_quota["errorCode"] == ErrorCode.QUOTA_EXCEEDED


async def test_files_mcp_upload_conflict_and_overwrite(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """`upload_document` rejects conflicts by default (`CONFLICT`) and replaces when `overwrite=True`."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with mcp_session(mcp_url, auth_headers) as session:
        first = await call_mcp_tool(
            session,
            "upload_document",
            {"directory_path": "/INBOX", "file_name": "notes.md", "content": "v1"},
        )
        assert first["success"] is True

        conflict = await call_mcp_tool(
            session,
            "upload_document",
            {"directory_path": "/INBOX", "file_name": "notes.md", "content": "v2"},
        )
        assert conflict["success"] is False
        assert conflict["errorCode"] == ErrorCode.CONFLICT

        replaced = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "notes.md",
                "content": "v2 updated",
                "overwrite": True,
            },
        )
        assert replaced["success"] is True
        assert replaced["file"]["file_id"] == first["file"]["file_id"]
        assert replaced["file"]["md5"] == hashlib.md5(b"v2 updated").hexdigest()
