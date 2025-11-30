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


async def test_query_server(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.get("/api/file/query/server")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_equipment_unlink(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post("/api/terminal/equipment/unlink", json={
        "equipmentNo": "SN123456",
        "version": "202407"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_check_user_exists(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post("/api/official/user/check/exists/server", json={
        "email": "test@example.com",
        "version": "202407"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}


async def test_auth_flow(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())

    # 1. CSRF
    resp = await client.get("/api/csrf")
    assert resp.status == 200
    assert "X-XSRF-TOKEN" in resp.headers

    # 2. Query Token
    resp = await client.post("/api/user/query/token")
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # 3. Random Code
    resp = await client.post("/api/official/user/query/random/code", json={"account": "test@example.com"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "randomCode" in data
    assert "timestamp" in data

    # 4. Login (Equipment)
    resp = await client.post("/api/official/user/account/login/equipment", json={
        "account": "test@example.com",
        "password": "hashed_password",
        "timestamp": data["timestamp"],
        "equipmentNo": "SN123456"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "token" in data
    assert "userName" in data
    assert "isBind" in data


async def test_bind_equipment(aiohttp_client: AiohttpClient) -> None:
    client = await aiohttp_client(create_app())
    resp = await client.post("/api/terminal/user/bindEquipment", json={
        "account": "test@example.com",
        "equipmentNo": "SN123456",
        "flag": "1",
        "name": "Supernote A6 X2 Nomad"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True}
