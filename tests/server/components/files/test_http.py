"""Integration tests for presigned binary uploads (`create_upload_url` -> `PUT /api/extended/uploads/{token}`)."""

from __future__ import annotations

import asyncio
import hashlib
import urllib.parse
from typing import Any
from unittest.mock import patch

import pytest

from supernote.models.base import ErrorCode
from supernote.server.components.files import mcp as files_mcp
from supernote.server.components.files import upload as files_upload
from supernote.server.events import VfsItemCreatedEvent
from supernote.server.keys import CONFIG_KEY, EVENT_BUS_KEY, FILE_SERVICE_KEY
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


def _relative_path(upload_url: str) -> str:
    parsed = urllib.parse.urlsplit(upload_url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


async def test_presigned_upload_happy_path_and_single_use_replay(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
    test_users: list[str],
) -> None:
    """`create_upload_url` -> `PUT` raw binary PDF commits to VFS, emits event, and rejects replay."""
    file_service = client.app[FILE_SERVICE_KEY]
    event_bus = client.app[EVENT_BUS_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    created_events: list[VfsItemCreatedEvent] = []

    async def _on_created(ev: VfsItemCreatedEvent) -> None:
        created_events.append(ev)

    event_bus.subscribe(VfsItemCreatedEvent, _on_created)

    pdf_bytes = b"%PDF-1.4\n" + bytes(range(256)) * 120  # ~30 KB binary PDF
    expected_md5 = hashlib.md5(pdf_bytes).hexdigest()

    async with mcp_session(mcp_url, auth_headers) as session:
        minted = await call_mcp_tool(
            session,
            "create_upload_url",
            {
                "directory_path": "/INBOX",
                "file_name": "paper.pdf",
                "expected_md5": expected_md5,
                "expected_size": len(pdf_bytes),
                "reason": "deliver binary pdf to inbox",
            },
        )
        assert minted["success"] is True
        assert minted["method"] == "PUT"
        assert minted["max_bytes"] == files_upload.MAX_UPLOAD_BYTES
        assert minted["expires_at"].endswith("Z")

        target = _relative_path(minted["upload_url"])
        # No Authorization header needed — token is the single-use capability
        resp = await client.put(target, data=pdf_bytes)
        assert resp.status == 200, await resp.text()
        body = await resp.json()
        await asyncio.sleep(0)

        assert body["success"] is True
        assert body["file"]["name"] == "paper.pdf"
        assert body["file"]["path"] == "/INBOX/paper.pdf"
        assert body["file"]["size"] == len(pdf_bytes)
        assert body["file"]["md5"] == expected_md5

        assert len(created_events) == 1
        assert created_events[0].user_id == test_user_id
        assert created_events[0].name == "paper.pdf"

        # Single-use replay is rejected with 404
        replay = await client.put(target, data=pdf_bytes)
        assert replay.status == 404


async def test_presigned_upload_rejects_md5_and_size_mismatch_without_writing(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """MD5 or size mismatch returns 400 and does not write any file to VFS."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    payload = b"%PDF-1.4 actual bytes"

    async with mcp_session(mcp_url, auth_headers) as session:
        # MD5 mismatch
        minted_md5 = await call_mcp_tool(
            session,
            "create_upload_url",
            {
                "directory_path": "/INBOX",
                "file_name": "bad_md5.pdf",
                "expected_md5": "a" * 32,
            },
        )
        resp_md5 = await client.put(
            _relative_path(minted_md5["upload_url"]), data=payload
        )
        assert resp_md5.status == 400
        md5_body = await resp_md5.json()
        assert md5_body["success"] is False
        assert "MD5 mismatch" in md5_body["errorMsg"]

        # Size mismatch
        minted_size = await call_mcp_tool(
            session,
            "create_upload_url",
            {
                "directory_path": "/INBOX",
                "file_name": "bad_size.pdf",
                "expected_size": len(payload) + 5,
            },
        )
        resp_size = await client.put(
            _relative_path(minted_size["upload_url"]), data=payload
        )
        assert resp_size.status == 400
        size_body = await resp_size.json()
        assert size_body["success"] is False
        assert "size mismatch" in size_body["errorMsg"]

    assert await file_service.list_folder(test_users[0], "/INBOX") == []


async def test_presigned_upload_rejects_oversized_body_and_unknown_token(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """Payloads exceeding max_bytes return 413 and unknown/expired tokens return 404."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    unknown = await client.put("/api/extended/uploads/does-not-exist", data=b"hi")
    assert unknown.status == 404

    with patch.object(files_mcp, "MAX_UPLOAD_BYTES", 8):
        async with mcp_session(mcp_url, auth_headers) as session:
            # expected_size above limit rejected up front
            too_big_arg = await call_mcp_tool(
                session,
                "create_upload_url",
                {
                    "directory_path": "/INBOX",
                    "file_name": "big.pdf",
                    "expected_size": 100,
                },
            )
            assert too_big_arg["success"] is False
            assert too_big_arg["errorCode"] == ErrorCode.BAD_REQUEST

            minted = await call_mcp_tool(
                session,
                "create_upload_url",
                {"directory_path": "/INBOX", "file_name": "big.pdf"},
            )
            assert minted["success"] is True

        resp = await client.put(
            _relative_path(minted["upload_url"]), data=b"0123456789"
        )
        assert resp.status == 413


async def test_presigned_upload_overwrite_conflict(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """`overwrite=False` rejects existing files both at mint time and at PUT commit time."""
    file_service = client.app[FILE_SERVICE_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    async with mcp_session(mcp_url, auth_headers) as session:
        # Mint two concurrent tokens before either commits
        first = await call_mcp_tool(
            session,
            "create_upload_url",
            {"directory_path": "/INBOX", "file_name": "dup.pdf", "overwrite": False},
        )
        second = await call_mcp_tool(
            session,
            "create_upload_url",
            {"directory_path": "/INBOX", "file_name": "dup.pdf", "overwrite": False},
        )
        assert first["success"] is True
        assert second["success"] is True

        resp1 = await client.put(_relative_path(first["upload_url"]), data=b"v1")
        assert resp1.status == 200

        # Second concurrent PUT hits 409 Conflict
        resp2 = await client.put(_relative_path(second["upload_url"]), data=b"v2")
        assert resp2.status == 409

        # Subsequent mint with overwrite=False fails up front with CONFLICT
        third = await call_mcp_tool(
            session,
            "create_upload_url",
            {"directory_path": "/INBOX", "file_name": "dup.pdf", "overwrite": False},
        )
        assert third["success"] is False
        assert third["errorCode"] == ErrorCode.CONFLICT


async def test_presigned_upload_respects_public_base_url_and_forwarded_headers(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_users: list[str],
) -> None:
    """`create_upload_url` uses configured public base_url or X-Forwarded-* headers behind a proxy."""
    file_service = client.app[FILE_SERVICE_KEY]
    config = client.app[CONFIG_KEY]
    await file_service.create_directory(test_users[0], "/INBOX")

    # 1. Explicit configured_base_url takes priority
    orig_base = config._base_url
    config._base_url = "https://notes.example.com/"
    try:
        async with mcp_session(mcp_url, auth_headers) as session:
            minted = await call_mcp_tool(
                session,
                "create_upload_url",
                {"directory_path": "/INBOX", "file_name": "proxy.pdf"},
            )
            assert minted["success"] is True
            assert minted["upload_url"].startswith(
                "https://notes.example.com/api/extended/uploads/"
            )
    finally:
        config._base_url = orig_base

    # X-Forwarded-Proto / X-Forwarded-Host fallback when base_url is unset
    assert (
        files_mcp._resolve_public_base_url(
            None,
            "http://127.0.0.1:8080",
            {
                "x-forwarded-proto": "https",
                "x-forwarded-host": "cloud.example.org",
            },
        )
        == "https://cloud.example.org"
    )
