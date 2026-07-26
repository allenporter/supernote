"""Tests for supernote.client.auth module."""

import pickle
from pathlib import Path

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import Client
from supernote.client.auth import ConstantAuth, FileCacheAuth
from supernote.client.exceptions import UnauthorizedException
from supernote.models.base import BaseResponse


async def test_constant_auth() -> None:
    """Test ConstantAuth class methods and properties."""
    auth = ConstantAuth("my-secret-token")
    assert await auth.async_get_access_token() == "my-secret-token"
    assert auth.token == "my-secret-token"


async def test_file_cache_auth_nonexistent_file(tmp_path: Path) -> None:
    """Test FileCacheAuth when cache file does not exist."""
    cache_file = str(tmp_path / "nonexistent" / "cache.pkl")
    auth = FileCacheAuth(cache_file)
    assert auth.get_host() is None
    assert await auth.async_get_access_token() == ""


async def test_file_cache_auth_save_and_load(tmp_path: Path) -> None:
    """Test FileCacheAuth saving credentials and loading them back."""
    cache_file = str(tmp_path / "sub_dir" / "cache.pkl")
    auth = FileCacheAuth(cache_file)
    auth.save_credentials("test-token-123", "https://cloud.supernote.com")

    assert (tmp_path / "sub_dir" / "cache.pkl").exists()
    assert auth.get_host() == "https://cloud.supernote.com"
    assert await auth.async_get_access_token() == "test-token-123"

    # Reload from cache file
    auth2 = FileCacheAuth(cache_file)
    assert await auth2.async_get_access_token() == "test-token-123"
    assert auth2.get_host() == "https://cloud.supernote.com"


async def test_file_cache_auth_invalid_pickle(tmp_path: Path) -> None:
    """Test FileCacheAuth with corrupted pickle file."""
    cache_file = tmp_path / "corrupt.pkl"
    cache_file.write_bytes(b"invalid pickle data")

    auth = FileCacheAuth(str(cache_file))
    assert auth.get_host() is None
    assert await auth.async_get_access_token() == ""


async def test_file_cache_auth_not_a_dict(tmp_path: Path) -> None:
    """Test FileCacheAuth with pickled non-dict object."""
    cache_file = tmp_path / "not_dict.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump(["not", "a", "dict"], f)

    auth = FileCacheAuth(str(cache_file))
    assert auth.get_host() is None
    assert await auth.async_get_access_token() == ""


async def test_file_cache_auth_missing_host(tmp_path: Path) -> None:
    """Test FileCacheAuth with pickled dict missing host."""
    cache_file = tmp_path / "missing_host.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump({"access_token": "token123"}, f)

    auth = FileCacheAuth(str(cache_file))
    assert auth.get_host() is None
    assert await auth.async_get_access_token() == "token123"


async def test_file_cache_auth_missing_token(tmp_path: Path) -> None:
    """Test FileCacheAuth with pickled dict missing access_token."""
    cache_file = tmp_path / "missing_token.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump({"host": "http://example.com"}, f)

    with pytest.raises(KeyError):
        FileCacheAuth(str(cache_file))


async def test_auth_expiration_unauthorized(aiohttp_client: AiohttpClient) -> None:
    """Test handling of expired authentication token (401 Unauthorized)."""

    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    async def handler_expired(request: web.Request) -> web.Response:
        return web.Response(status=401, text="Token Expired")

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/api/protected", handler_expired)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    auth = ConstantAuth("expired-token")
    client = Client(test_client.session, host=base_url, auth=auth)

    with pytest.raises(UnauthorizedException):
        await client.get_json("/api/protected", BaseResponse)


async def test_token_refresh_flow(tmp_path: Path) -> None:
    """Test updating token in cache when refreshed."""
    cache_file = str(tmp_path / "auth.pkl")
    auth = FileCacheAuth(cache_file)

    assert await auth.async_get_access_token() == ""

    # Save refreshed token credentials
    auth.save_credentials("refreshed-token-xyz", "https://api.supernote.com")
    assert await auth.async_get_access_token() == "refreshed-token-xyz"
    assert auth.get_host() == "https://api.supernote.com"
