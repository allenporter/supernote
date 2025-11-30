from unittest.mock import patch
from pathlib import Path
from typing import Callable, Awaitable

from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.app import create_app

# Type alias for the aiohttp_client fixture
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


async def test_server_root(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Supernote Private Cloud Server" in text


async def test_trace_logging(aiohttp_client: AiohttpClient, tmp_path: Path) -> None:
    # Mock config to use a temporary log file
    log_file = tmp_path / "trace.log"

    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        client = await aiohttp_client(create_app())
        await client.get("/some/random/path")

    assert log_file.exists()
    content = log_file.read_text()
    assert "/some/random/path" in content
    assert "GET" in content
