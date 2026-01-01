"""Tests for the cloud client."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable

import aiohttp.test_utils
import pytest
from aiohttp import web

from supernote.models.file import FileListQueryVO
from supernote.client import Client
from supernote.client.cloud_client import SupernoteClient


@dataclass
class SimpleResponse(FileListQueryVO):
    """Simple response for testing."""

    data: dict = field(default_factory=dict)


async def handler_csrf(request: web.Request) -> web.Response:
    """Handle CSRF request."""
    # Ensure headers are returned in the response
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


async def handler_file_list(request: web.Request) -> web.Response:
    """Handle file list request."""
    return web.json_response(
        {
            "success": True,
            "total": 2,
            "size": 2,
            "pages": 1,
            "userFileVOList": [
                {
                    "id": 1,
                    "fileName": "file1.note",
                    "directoryId": 0,
                    "isFolder": "N",
                    "createTime": 123456,
                    "updateTime": 123456,
                },
                {
                    "id": 2,
                    "fileName": "file2.note",
                    "directoryId": 0,
                    "isFolder": "N",
                    "createTime": 123456,
                    "updateTime": 123456,
                },
            ],
        }
    )


async def handler_download_url(request: web.Request) -> web.Response:
    """Handle download URL request."""
    return web.json_response(
        {"success": True, "url": "http://localhost:8080/download/1"}
    )


async def handler_download_content(request: web.Request) -> web.Response:
    """Handle file content download."""
    return web.Response(body=b"file_content")


@pytest.fixture(name="client")
async def client_fixture(
    aiohttp_client: Callable[
        [web.Application], Awaitable[aiohttp.test_utils.TestClient]
    ],
) -> SupernoteClient:
    """Fixture for SupernoteClient instance."""
    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/file/list/query", handler_file_list)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    return SupernoteClient(client)


async def test_file_list(client: SupernoteClient) -> None:
    """Test file listing."""
    response = await client.file_list(directory_id=0)
    assert response.success
    assert response.total == 2
    assert len(response.user_file_vo_list) == 2
    assert response.user_file_vo_list[0].file_name == "file1.note"


@pytest.fixture(name="client_with_relative_download")
async def client_relative_download_fixture(
    aiohttp_client: Callable[
        [web.Application], Awaitable[aiohttp.test_utils.TestClient]
    ],
) -> SupernoteClient:
    """Fixture for SupernoteClient instance with relative download URL."""

    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    async def handler_download_url_relative(request: web.Request) -> web.Response:
        return web.json_response({"success": True, "url": "/download/1"})

    async def handler_download_content(request: web.Request) -> web.Response:
        return web.Response(body=b"file_content")

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/file/download/url", handler_download_url_relative)
    app.router.add_get("/download/1", handler_download_content)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    return SupernoteClient(client)


async def test_file_download_relative(
    client_with_relative_download: SupernoteClient,
) -> None:
    """Test file download with relative URL."""
    content = await client_with_relative_download.file_download(file_id=1)
    assert content == b"file_content"
