"""MCP protocol tests for `supernote.server.components.files.mcp`."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import urllib.parse
from typing import Any

import aiohttp
import pytest
from sqlalchemy import update

from supernote.models.base import ErrorCode
from supernote.server.components.files import mcp as files_mcp
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import VfsItemCreatedEvent
from supernote.server.keys import EVENT_BUS_KEY, FILE_SERVICE_KEY, USER_SERVICE_KEY
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


async def _upload_to_signed_url(
    client: Any, upload_url: str, file_name: str, content: bytes
) -> dict[str, Any]:
    """POST multipart bytes to the signed `/api/oss/upload` URL via the aiohttp test client."""
    parsed = urllib.parse.urlsplit(upload_url)
    target = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    form = aiohttp.FormData()
    form.add_field(
        "file",
        content,
        filename=file_name,
        content_type="application/octet-stream",
    )
    resp = await client.post(target, data=form)
    assert resp.status == 200, await resp.text()
    data: dict[str, Any] = await resp.json()
    return data


async def test_files_mcp_staged_upload_roundtrip_and_list_files(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Full end-to-end staged PDF upload via `prepare_upload` -> `/api/oss/upload` -> `commit_upload` -> `list_files`."""
    file_service = client.app[FILE_SERVICE_KEY]
    event_bus = client.app[EVENT_BUS_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    created_events: list[VfsItemCreatedEvent] = []

    async def _on_created(ev: VfsItemCreatedEvent) -> None:
        created_events.append(ev)

    event_bus.subscribe(VfsItemCreatedEvent, _on_created)

    pdf_bytes = b"%PDF-1.4\nhello supernote inbox\n"
    expected_md5 = hashlib.md5(pdf_bytes).hexdigest()

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        assert {
            "list_files",
            "upload_document",
            "prepare_upload",
            "commit_upload",
        }.issubset(tool_names)

        prep = await call_mcp_tool(
            session,
            "prepare_upload",
            {
                "directory_path": "/INBOX",
                "file_name": "paper.pdf",
                "size": len(pdf_bytes),
            },
        )
        assert prep["success"] is True
        assert prep["method"] == "POST"
        assert prep["field_name"] == "file"
        assert prep["expires_in"] > 0
        upload_token = prep["upload_token"]
        upload_url = prep["upload_url"]

        oss_resp = await _upload_to_signed_url(
            client, upload_url, "paper.pdf", pdf_bytes
        )
        assert oss_resp["md5"] == expected_md5

        # Wrong MD5 returns BAD_REQUEST without burning the upload token
        bad_md5 = await call_mcp_tool(
            session,
            "commit_upload",
            {"upload_token": upload_token, "md5": "0" * 32},
        )
        assert bad_md5["success"] is False
        assert bad_md5["errorCode"] == ErrorCode.BAD_REQUEST

        # Retrying with the right MD5 commits and emits VfsItemCreatedEvent
        committed = await call_mcp_tool(
            session,
            "commit_upload",
            {
                "upload_token": upload_token,
                "md5": oss_resp["md5"],
                "reason": "drop research pdf into inbox",
            },
        )
        await asyncio.sleep(0)

        assert committed["success"] is True
        assert committed["file"]["name"] == "paper.pdf"
        assert committed["file"]["path"] == "/INBOX/paper.pdf"
        assert committed["file"]["is_folder"] is False
        assert committed["file"]["size"] == len(pdf_bytes)
        assert committed["file"]["md5"] == expected_md5

        assert len(created_events) == 1
        assert created_events[0].user_id == test_user_id
        assert created_events[0].name == "paper.pdf"

        # Token is consumed after successful commit
        replay = await call_mcp_tool(
            session,
            "commit_upload",
            {"upload_token": upload_token, "md5": expected_md5},
        )
        assert replay["success"] is False
        assert replay["errorCode"] == ErrorCode.NOT_FOUND

        # list_files returns the uploaded file in flat and recursive modes
        inbox_list = await call_mcp_tool(session, "list_files", {"path": "/INBOX"})
        assert inbox_list["success"] is True
        assert [i["name"] for i in inbox_list["items"]] == ["paper.pdf"]

        recursive_list = await call_mcp_tool(
            session, "list_files", {"path": "/", "recursive": True}
        )
        assert recursive_list["success"] is True
        assert any(i["path"] == "/INBOX/paper.pdf" for i in recursive_list["items"])


async def test_files_mcp_upload_token_user_isolation(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_users: list[str],
) -> None:
    """Another user cannot commit or invalidate the owner's staged upload token."""
    file_service = client.app[FILE_SERVICE_KEY]
    user_service = client.app[USER_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with session_manager.session() as db_session:
        other_user = UserDO(
            email="other@example.com",
            password_md5="unused",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.commit()
        await db_session.refresh(other_user)

    other_token, _ = await user_service.create_api_key(other_user.id, "other-mcp-key")
    other_headers = {"x-access-token": other_token}

    payload = b"private pdf"
    md5 = hashlib.md5(payload).hexdigest()

    async with mcp_session(mcp_url, auth_headers) as owner_session:
        prep = await call_mcp_tool(
            owner_session,
            "prepare_upload",
            {
                "directory_path": "/INBOX",
                "file_name": "secret.pdf",
                "size": len(payload),
            },
        )
        assert prep["success"] is True
        await _upload_to_signed_url(client, prep["upload_url"], "secret.pdf", payload)

        # User B attempts to commit User A's upload token -> rejected
        async with mcp_session(mcp_url, other_headers) as other_session:
            hijack = await call_mcp_tool(
                other_session,
                "commit_upload",
                {"upload_token": prep["upload_token"], "md5": md5},
            )
            assert hijack["success"] is False
            assert hijack["errorCode"] == ErrorCode.NOT_FOUND

        # User A's token still works
        committed = await call_mcp_tool(
            owner_session,
            "commit_upload",
            {"upload_token": prep["upload_token"], "md5": md5},
        )
        assert committed["success"] is True
        assert committed["file"]["name"] == "secret.pdf"


async def test_files_mcp_validation_and_quota_errors(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Verify validation errors, missing paths, and quota enforcement over MCP."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with mcp_session(mcp_url, auth_headers) as session:
        # list_files on missing directory
        missing = await call_mcp_tool(session, "list_files", {"path": "/NO_SUCH_DIR"})
        assert missing["success"] is False
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

        # prepare_upload with invalid file_name and negative size
        bad_name = await call_mcp_tool(
            session,
            "prepare_upload",
            {"directory_path": "/INBOX", "file_name": "sub/paper.pdf", "size": 10},
        )
        assert bad_name["success"] is False
        assert bad_name["errorCode"] == ErrorCode.BAD_REQUEST

        bad_size = await call_mcp_tool(
            session,
            "prepare_upload",
            {"directory_path": "/INBOX", "file_name": "paper.pdf", "size": -5},
        )
        assert bad_size["success"] is False
        assert bad_size["errorCode"] == ErrorCode.BAD_REQUEST

        # prepare_upload into non-existent directory
        missing_dir = await call_mcp_tool(
            session,
            "prepare_upload",
            {"directory_path": "/MISSING", "file_name": "paper.pdf", "size": 10},
        )
        assert missing_dir["success"] is False
        assert missing_dir["errorCode"] == ErrorCode.NOT_FOUND

        # commit_upload before uploading bytes -> NOT_FOUND
        prep = await call_mcp_tool(
            session,
            "prepare_upload",
            {"directory_path": "/INBOX", "file_name": "never_uploaded.pdf", "size": 10},
        )
        assert prep["success"] is True
        no_blob = await call_mcp_tool(
            session,
            "commit_upload",
            {"upload_token": prep["upload_token"], "md5": "a" * 32},
        )
        assert no_blob["success"] is False
        assert no_blob["errorCode"] == ErrorCode.NOT_FOUND

        # Quota exceeded on prepare_upload
        async with session_manager.session() as db_session:
            await db_session.execute(
                update(UserDO).where(UserDO.id == test_user_id).values(total_capacity=5)
            )
            await db_session.commit()

        over_quota = await call_mcp_tool(
            session,
            "prepare_upload",
            {"directory_path": "/INBOX", "file_name": "big.pdf", "size": 100},
        )
        assert over_quota["success"] is False
        assert over_quota["errorCode"] == ErrorCode.QUOTA_EXCEEDED


async def test_files_mcp_upload_document_utf8_and_base64(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """`upload_document` uploads UTF-8 text and base64 binary payloads directly over MCP."""
    file_service = client.app[FILE_SERVICE_KEY]
    event_bus = client.app[EVENT_BUS_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    created_events: list[VfsItemCreatedEvent] = []

    async def _on_created(ev: VfsItemCreatedEvent) -> None:
        created_events.append(ev)

    event_bus.subscribe(VfsItemCreatedEvent, _on_created)

    md_text = "# Research Brief\n\nSummary for e-ink reading.\n"
    pdf_bytes = b"%PDF-1.4 inline pdf"

    async with mcp_session(mcp_url, auth_headers) as session:
        md_res = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "brief.md",
                "content": md_text,
                "reason": "deliver brief from mcp-only client",
            },
        )
        assert md_res["success"] is True
        assert md_res["file"]["path"] == "/INBOX/brief.md"
        assert md_res["file"]["size"] == len(md_text.encode("utf-8"))
        assert md_res["file"]["md5"] == hashlib.md5(md_text.encode("utf-8")).hexdigest()

        pdf_res = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "small.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
                "encoding": "base64",
            },
        )
        await asyncio.sleep(0)

        assert pdf_res["success"] is True
        assert pdf_res["file"]["path"] == "/INBOX/small.pdf"
        assert pdf_res["file"]["size"] == len(pdf_bytes)
        assert pdf_res["file"]["md5"] == hashlib.md5(pdf_bytes).hexdigest()
        assert len(created_events) == 2
        assert all(ev.user_id == test_user_id for ev in created_events)

        # Invalid base64 & unsupported encoding rejected
        bad_b64 = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "bad.pdf",
                "content": "not-valid-base64!!!",
                "encoding": "base64",
            },
        )
        assert bad_b64["success"] is False
        assert bad_b64["errorCode"] == ErrorCode.BAD_REQUEST

        bad_enc = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "bad.txt",
                "content": "hello",
                "encoding": "latin-1",
            },
        )
        assert bad_enc["success"] is False
        assert bad_enc["errorCode"] == ErrorCode.BAD_REQUEST

        # Size limit enforced
        monkeypatch.setattr(files_mcp, "MAX_INLINE_UPLOAD_BYTES", 8)
        too_big = await call_mcp_tool(
            session,
            "upload_document",
            {
                "directory_path": "/INBOX",
                "file_name": "too_big.txt",
                "content": "0123456789",
            },
        )
        assert too_big["success"] is False
        assert too_big["errorCode"] == ErrorCode.BAD_REQUEST
