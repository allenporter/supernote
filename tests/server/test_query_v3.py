import pytest
from pathlib import Path
from typing import Callable, Awaitable
from aiohttp.test_utils import TestClient
from aiohttp.web import Application
from supernote.server.app import create_app

AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture(autouse=True)
async def test_query_v3_success(
    aiohttp_client: AiohttpClient,
    mock_storage: Path,
    auth_headers: dict[str, str],
) -> None:
    # Create a test file
    test_file = mock_storage / "Note" / "test.note"
    test_file.write_text("content")

    client = await aiohttp_client(create_app())

    # Query by ID (relative path)
    resp = await client.post(
        "/api/file/3/files/query_v3",
        json={"equipmentNo": "SN123", "id": "Note/test.note"},
        headers=auth_headers,
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["entriesVO"]["id"] == "Note/test.note"
    assert data["entriesVO"]["name"] == "test.note"
    assert data["entriesVO"]["path_display"] == "/Note/test.note"
    # MD5 of "content" is 9a0364b9e99bb480dd25e1f0284c8555
    assert data["entriesVO"]["content_hash"] == "9a0364b9e99bb480dd25e1f0284c8555"


async def test_query_v3_not_found(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    client = await aiohttp_client(create_app())

    resp = await client.post(
        "/api/file/3/files/query_v3",
        json={"equipmentNo": "SN123", "id": "Note/missing.note"},
        headers=auth_headers,
    )

    assert resp.status == 200
    data = await resp.json()
    assert data == {
        "success": True,
        "equipmentNo": "SN123",
    }
