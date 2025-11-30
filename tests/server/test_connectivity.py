import pytest
from unittest.mock import patch
from pathlib import Path
from typing import Callable, Awaitable

from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.app import create_app

# Type alias for the aiohttp_client fixture
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> str:
    log_file = tmp_path / "trace.log"
    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        yield str(log_file)


async def test_server_root(aiohttp_client: AiohttpClient, mock_trace_log: str) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Supernote Private Cloud Server" in text


async def test_trace_logging(
    aiohttp_client: AiohttpClient, mock_trace_log: str
) -> None:
    client = await aiohttp_client(create_app())
    await client.get("/some/random/path")

    log_file = Path(mock_trace_log)
    assert log_file.exists()
    content = log_file.read_text()
    assert "/some/random/path" in content
    assert "GET" in content
