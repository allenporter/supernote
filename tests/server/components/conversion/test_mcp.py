"""MCP protocol tests for `supernote.server.components.conversion.mcp`."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image
from prometheus_client import REGISTRY

from supernote.models.user import UserRegisterDTO
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import BLOB_STORAGE_KEY
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_page_png_path
from tests.server.components.conftest import mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


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


def _make_png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(30, 60, 90)).save(buf, format="PNG")
    return buf.getvalue()


async def test_get_page_image_returns_cached_note_png_and_downscales(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify `get_page_image` returns cached PNG as `ImageContent` and respects `max_dimension`."""
    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            directory_id=0,
            file_name="journal.note",
            storage_key="journal_key",
        )
        db.add(file_do)
        await db.flush()
        db.add(
            NotePageContentDO(
                file_id=file_do.id,
                page_index=0,
                page_id="P20260115090000a",
                text_content="First page notes.",
            )
        )
        await db.commit()
        file_id = int(file_do.id)

    blob_storage = client.app[BLOB_STORAGE_KEY]
    png_key = get_page_png_path(file_id, "P20260115090000a")
    await blob_storage.put(CACHE_BUCKET, png_key, _make_png((1600, 800)))

    before_ok = _call_count("get_page_image", "success")
    before_dur = _duration_count("get_page_image")

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert "get_page_image" in {t.name for t in tools.tools}

        result = await session.call_tool(
            "get_page_image",
            arguments={
                "file_id": str(file_id),
                "page_index": 0,
                "max_dimension": 400,
            },
        )

    assert result.is_error is False
    assert len(result.content) == 2
    assert isinstance(result.content[0], TextContent)
    assert "journal.note" in result.content[0].text
    assert "dimensions=400x200" in result.content[0].text
    assert isinstance(result.content[1], ImageContent)
    assert result.content[1].mime_type == "image/png"

    decoded_bytes = base64.b64decode(result.content[1].data)
    with Image.open(io.BytesIO(decoded_bytes)) as img:
        assert img.format == "PNG"
        assert img.size == (400, 200)

    assert _call_count("get_page_image", "success") == before_ok + 1.0
    assert _duration_count("get_page_image") == before_dur + 1.0


async def test_get_page_image_renders_uncached_note_page_on_demand(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify `get_page_image` renders a real `.note` page on demand when not yet cached."""
    sample_note = Path("tests/testdata/20251207_221454.note").read_bytes()
    storage_key = f"notes/{hashlib.md5(sample_note).hexdigest()}.note"
    await client.app[BLOB_STORAGE_KEY].put(USER_DATA_BUCKET, storage_key, sample_note)

    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            directory_id=0,
            file_name="ondemand.note",
            storage_key=storage_key,
            md5=hashlib.md5(sample_note).hexdigest(),
        )
        db.add(file_do)
        await db.commit()
        file_id = int(file_do.id)

    async with mcp_session(mcp_url, auth_headers) as session:
        result = await session.call_tool(
            "get_page_image",
            arguments={
                "file_id": str(file_id),
                "page_index": 0,
                "max_dimension": 512,
            },
        )

    assert result.is_error is False
    assert isinstance(result.content[1], ImageContent)
    decoded_bytes = base64.b64decode(result.content[1].data)
    with Image.open(io.BytesIO(decoded_bytes)) as img:
        assert img.format == "PNG"
        assert max(img.size) <= 512


async def test_get_page_image_serves_standalone_image_and_rejects_nonzero_page(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify standalone JPEG images are normalized to PNG and reject `page_index != 0`."""
    buf = io.BytesIO()
    Image.new("RGB", (600, 300), color=(200, 100, 50)).save(buf, format="JPEG")
    jpg_bytes = buf.getvalue()
    storage_key = "images/whiteboard.jpg"
    await client.app[BLOB_STORAGE_KEY].put(USER_DATA_BUCKET, storage_key, jpg_bytes)

    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            directory_id=0,
            file_name="whiteboard.jpg",
            storage_key=storage_key,
            md5=hashlib.md5(jpg_bytes).hexdigest(),
        )
        db.add(file_do)
        await db.commit()
        file_id = str(file_do.id)

    async with mcp_session(mcp_url, auth_headers) as session:
        ok_result = await session.call_tool(
            "get_page_image",
            arguments={"file_id": file_id, "max_dimension": 300},
        )
        bad_page = await session.call_tool(
            "get_page_image",
            arguments={"file_id": file_id, "page_index": 1},
        )

    assert ok_result.is_error is False
    assert isinstance(ok_result.content[1], ImageContent)
    decoded_bytes = base64.b64decode(ok_result.content[1].data)
    with Image.open(io.BytesIO(decoded_bytes)) as img:
        assert img.format == "PNG"
        assert img.size == (300, 150)

    assert bad_page.is_error is True
    assert isinstance(bad_page.content[0], TextContent)
    assert json.loads(bad_page.content[0].text)["errorCode"] == "404"


async def test_get_page_image_enforces_access_and_validation(
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify `get_page_image` enforces user isolation, active/file checks, and parameter bounds."""
    other_account = await user_service.register(
        UserRegisterDTO(email="other_image_mcp@example.com", password="a" * 32)
    )
    async with session_manager.session() as db:
        other_user = UserFileDO(
            user_id=other_account.id,
            file_name="secret.png",
            directory_id=0,
            is_active="Y",
            storage_key="secret_img_key",
        )
        deleted = UserFileDO(
            user_id=test_user_id,
            file_name="deleted.png",
            directory_id=0,
            is_active="N",
            storage_key="deleted_img_key",
        )
        folder = UserFileDO(
            user_id=test_user_id,
            file_name="MyFolder",
            directory_id=0,
            is_active="Y",
            is_folder="Y",
        )
        unsupported = UserFileDO(
            user_id=test_user_id,
            file_name="readme.txt",
            directory_id=0,
            is_active="Y",
            storage_key="readme_key",
        )
        db.add_all([other_user, deleted, folder, unsupported])
        await db.commit()
        other_id = str(other_user.id)
        deleted_id = str(deleted.id)
        folder_id = str(folder.id)
        unsupported_id = str(unsupported.id)

    before_fail = _call_count("get_page_image", "failure")
    cases = [
        ({"file_id": "abc"}, "400"),
        ({"file_id": "1", "page_index": -1}, "400"),
        ({"file_id": "1", "max_dimension": 16}, "400"),
        ({"file_id": "1", "max_dimension": 4096}, "400"),
        ({"file_id": other_id}, "404"),
        ({"file_id": deleted_id}, "404"),
        ({"file_id": folder_id}, "404"),
        ({"file_id": unsupported_id}, "400"),
    ]

    async with mcp_session(mcp_url, auth_headers) as session:
        for args, expected_code in cases:
            res = await session.call_tool("get_page_image", arguments=args)
            assert res.is_error is True
            assert isinstance(res.content[0], TextContent)
            payload = json.loads(res.content[0].text)
            assert payload["success"] is False
            assert payload["errorCode"] == expected_code

    assert _call_count("get_page_image", "failure") == before_fail + len(cases)
