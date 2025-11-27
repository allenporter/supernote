"""Tests for the client library."""

from dataclasses import dataclass

import pytest
import pytest_asyncio
from aiohttp import web
import aiohttp.test_utils

from supernote.cloud.api_model import BaseResponse
from supernote.cloud.client import Client
from supernote.cloud.exceptions import ApiException, ForbiddenException, UnauthorizedException
from supernote.cloud.auth import ConstantAuth


@dataclass
class SimpleResponse(BaseResponse):
    """Simple response for testing."""
    data: str = ""


async def handler_csrf(request: web.Request):
    """Handle CSRF request."""
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


async def handler_test_url(request: web.Request):
    """Handle test URL request."""
    if request.headers.get("X-XSRF-TOKEN") != "test-token":
        return web.Response(status=403)
    return web.json_response({"success": True, "data": "value"})


async def handler_post_url(request: web.Request):
    """Handle POST URL request."""
    if request.headers.get("X-XSRF-TOKEN") != "test-token":
        return web.Response(status=403)
    data = await request.json()
    return web.json_response({"success": True, "data": data.get("input")})


async def handler_401(request: web.Request):
    """Handle 401 request."""
    return web.Response(status=401, text="Unauthorized")


async def handler_403(request: web.Request):
    """Handle 403 request."""
    return web.Response(status=403, text="Forbidden")


async def handler_success_false(request: web.Request):
    """Handle success=False request."""
    return web.json_response({"success": False, "errorMsg": "Something went wrong"})


async def handler_auth_check(request: web.Request):
    """Handle auth check request."""
    if request.headers.get("x-access-token") == "my-token":
        return web.json_response({"success": True, "data": "authorized"})
    return web.Response(status=401)


async def handler_malformed_json(request: web.Request):
    """Handle malformed JSON response."""
    return web.Response(text="{invalid-json")


@pytest_asyncio.fixture(name="client")
async def client_fixture(aiohttp_client: aiohttp.test_utils.TestClient) -> Client:
    """Fixture for Client instance."""
    app = web.Application()
    app.router.add_get("/csrf", handler_csrf)
    app.router.add_get("/test-url", handler_test_url)
    app.router.add_post("/post-url", handler_post_url)
    app.router.add_get("/error-401", handler_401)
    app.router.add_get("/error-403", handler_403)
    app.router.add_get("/success-false", handler_success_false)
    app.router.add_get("/auth-check", handler_auth_check)
    app.router.add_post("/malformed-json", handler_malformed_json)

    test_client = await aiohttp_client(app)
    
    base_url = str(test_client.make_url(""))
    return Client(test_client.session, host=base_url.rstrip("/"))


async def test_get_json(client: Client):
    """Test get_json method."""

    response = await client.get_json("test-url", SimpleResponse)

    assert response.success
    assert response.data == "value"


async def test_post_json(client: Client):
    """Test post_json method."""
    @dataclass
    class PostRequest:
        input: str
        def to_dict(self): return {"input": self.input}

    response = await client.post_json("post-url", SimpleResponse, json={"input": "posted"})
    assert response.success
    assert response.data == "posted"


async def test_post_json_malformed(client: Client):
    """Test post_json with malformed response."""
    with pytest.raises(ApiException, match="Server return malformed response"):
        await client.post_json("malformed-json", SimpleResponse, json={})


async def test_unauthorized(client: Client):
    """Test 401 Unauthorized."""
    with pytest.raises(UnauthorizedException):
        await client.get_json("error-401", SimpleResponse)


async def test_forbidden(client: Client):
    """Test 403 Forbidden."""
    with pytest.raises(ForbiddenException):
        await client.get_json("error-403", SimpleResponse)


async def test_api_exception_success_false(client: Client):
    """Test API returning success=False."""
    with pytest.raises(ApiException, match="Something went wrong"):
        await client.get_json("success-false", SimpleResponse)


async def test_auth_token(aiohttp_client):
    """Test authentication token injection."""
    app = web.Application()
    app.router.add_get("/csrf", handler_csrf)
    app.router.add_get("/auth-check", handler_auth_check)
    
    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    
    auth = ConstantAuth("my-token")
    client = Client(test_client.session, host=base_url.rstrip("/"), auth=auth)
    
    response = await client.get_json("auth-check", SimpleResponse)
    assert response.success
    assert response.data == "authorized"
