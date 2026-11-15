"""Tests for the client library."""

import logging
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import Client
from supernote.client.auth import AbstractAuth, ConstantAuth
from supernote.client.exceptions import (
    ApiException,
    ForbiddenException,
    UnauthorizedException,
)
from supernote.models.base import BaseResponse


@dataclass
class SimpleResponse(BaseResponse):
    """Simple response for testing."""

    data: str = ""


async def handler_csrf(request: web.Request) -> web.Response:
    """Handle CSRF request."""
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


async def handler_test_url(request: web.Request) -> web.Response:
    """Handle test URL request."""
    if request.headers.get("X-XSRF-TOKEN") != "test-token":
        return web.Response(status=403)
    return web.json_response({"success": True, "data": "value"})


async def handler_post_url(request: web.Request) -> web.Response:
    """Handle POST URL request."""
    if request.headers.get("X-XSRF-TOKEN") != "test-token":
        return web.Response(status=403)
    data = await request.json()
    return web.json_response({"success": True, "data": data.get("input")})


async def handler_401(request: web.Request) -> web.Response:
    """Handle 401 request."""
    return web.Response(status=401, text="Unauthorized")


async def handler_403(request: web.Request) -> web.Response:
    """Handle 403 request."""
    return web.Response(status=403, text="Forbidden")


async def handler_success_false(request: web.Request) -> web.Response:
    """Handle success=False request."""
    return web.json_response({"success": False, "errorMsg": "Something went wrong"})


async def handler_auth_check(request: web.Request) -> web.Response:
    """Handle auth check request."""
    if request.headers.get("x-access-token") == "my-token":
        return web.json_response({"success": True, "data": "authorized"})
    return web.Response(status=401)


async def handler_malformed_json(request: web.Request) -> web.Response:
    """Handle malformed JSON response."""
    return web.Response(text="{invalid-json")


@pytest_asyncio.fixture(name="client")
async def client_fixture(aiohttp_client: AiohttpClient) -> Client:
    """Fixture for Client instance."""
    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/test-url", handler_test_url)
    app.router.add_post("/post-url", handler_post_url)
    app.router.add_get("/error-401", handler_401)
    app.router.add_get("/error-403", handler_403)
    app.router.add_get("/success-false", handler_success_false)
    app.router.add_get("/auth-check", handler_auth_check)
    app.router.add_post("/malformed-json", handler_malformed_json)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    return Client(test_client.session, host=base_url)


async def test_get_json(client: Client) -> None:
    """Test get_json method."""

    response = await client.get_json("test-url", SimpleResponse)

    assert response.success
    assert response.data == "value"


async def test_post_json(client: Client) -> None:
    """Test post_json method."""

    @dataclass
    class PostRequest:
        input: str

        def to_dict(self) -> dict[str, str]:
            return {"input": self.input}

    response = await client.post_json(
        "post-url", SimpleResponse, json={"input": "posted"}
    )
    assert response.success
    assert response.data == "posted"


async def test_post_json_malformed(client: Client) -> None:
    """Test post_json with malformed response."""
    with pytest.raises(ApiException, match="Server return malformed response"):
        await client.post_json("malformed-json", SimpleResponse, json={})


async def test_unauthorized(client: Client) -> None:
    """Test 401 Unauthorized."""
    with pytest.raises(UnauthorizedException):
        await client.get_json("error-401", SimpleResponse)


async def test_forbidden(client: Client) -> None:
    """Test 403 Forbidden."""
    with pytest.raises(ForbiddenException):
        await client.get_json("error-403", SimpleResponse)


async def test_api_exception_success_false(client: Client) -> None:
    """Test API returning success=False."""
    with pytest.raises(ApiException, match="Something went wrong"):
        await client.get_json("success-false", SimpleResponse)


async def test_auth_token(aiohttp_client: AiohttpClient) -> None:
    """Test authentication token injection."""
    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/auth-check", handler_auth_check)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    auth = ConstantAuth("my-token")
    client = Client(test_client.session, host=base_url, auth=auth)

    response = await client.get_json("/auth-check", SimpleResponse)
    assert response.success
    assert response.data == "authorized"


async def test_headers_with_referrer(aiohttp_client: AiohttpClient) -> None:
    """Test that headers include referrer given a host."""

    @dataclass
    class HeadersResponse(BaseResponse):
        data: dict[str, str] = field(default_factory=dict)

    async def handler_headers(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "success": True,
                "data": dict(request.headers),
            }
        )

    # Local CSRF handler to return token in headers as expected by Client
    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/headers", handler_headers)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    client = Client(test_client.session, host=base_url)

    response = await client.get_json("headers", HeadersResponse)
    assert response.success
    headers = response.data
    assert headers.get("Referer") == base_url
    assert headers.get("Origin") == base_url


async def test_auth_token_missing(aiohttp_client: AiohttpClient) -> None:
    """Test that empty access tokens are not injected into headers."""

    @dataclass
    class HeadersResponse(BaseResponse):
        data: dict[str, str] = field(default_factory=dict)

    async def handler_headers(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "success": True,
                "data": dict(request.headers),
            }
        )

    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/headers", handler_headers)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    class EmptyAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return ""

    client = Client(test_client.session, host=base_url, auth=EmptyAuth())

    response = await client.get_json("headers", HeadersResponse)
    assert response.success
    headers = response.data
    assert "x-access-token" not in headers


async def test_api_key_sends_authorization_bearer_header(
    aiohttp_client: AiohttpClient,
) -> None:
    """Test that static sn_... API keys send Authorization: Bearer rather than x-access-token."""

    @dataclass
    class HeadersResponse(BaseResponse):
        data: dict[str, str] = field(default_factory=dict)

    async def handler_headers(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "success": True,
                "data": dict(request.headers),
            }
        )

    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/headers", handler_headers)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    api_key = "sn_0123456789abcdef0123456789abcdef"
    client = Client(
        test_client.session,
        host=base_url,
        auth=ConstantAuth(api_key),
    )

    response = await client.get_json("headers", HeadersResponse)
    assert response.success
    headers = response.data
    assert headers.get("Authorization") == f"Bearer {api_key}"
    assert "x-access-token" not in headers


async def test_cross_origin_requests_strip_credentials_and_csrf(
    aiohttp_client: AiohttpClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify Client never sends Bearer/x-access-token/XSRF headers to cross-origin OSS URLs or debug logs."""

    @dataclass
    class HeadersResponse(BaseResponse):
        data: dict[str, str] = field(default_factory=dict)
        key: str = ""

    api_key = "sn_fedcba9876543210fedcba9876543210"

    async def handler_csrf(_request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "csrf-tok"})

    async def handler_same_origin(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "success": True,
                "data": dict(request.headers),
                "key": api_key,
            }
        )

    async def handler_external_oss(request: web.Request) -> web.Response:
        return web.json_response({"success": True, "data": dict(request.headers)})

    api_app = web.Application()
    api_app.router.add_get("/api/csrf", handler_csrf)
    api_app.router.add_get("/headers", handler_same_origin)

    oss_app = web.Application()
    oss_app.router.add_get("/presigned-blob", handler_external_oss)

    api_server = await aiohttp_client(api_app)
    oss_server = await aiohttp_client(oss_app)
    api_base = str(api_server.make_url(""))
    oss_url = str(oss_server.make_url("/presigned-blob?X-Amz-Signature=sig"))

    client = Client(
        api_server.session,
        host=api_base,
        auth=ConstantAuth(api_key),
    )

    with caplog.at_level(logging.DEBUG, logger="supernote.client.client"):
        # Full same-origin URL receives Authorization + X-XSRF-TOKEN, but debug logs redact raw key
        same_resp = await client.get_json(f"{api_base}/headers", HeadersResponse)
        assert same_resp.data.get("Authorization") == f"Bearer {api_key}"
        assert same_resp.data.get("X-XSRF-TOKEN") == "csrf-tok"
        assert api_key not in caplog.text

        # Cross-origin presigned OSS URL must NOT receive Authorization, x-access-token, X-XSRF-TOKEN, or Origin
        cross_resp = await client.get_json(oss_url, HeadersResponse)
        assert "Authorization" not in cross_resp.data
        assert "x-access-token" not in cross_resp.data
        assert "X-XSRF-TOKEN" not in cross_resp.data
        assert "Origin" not in cross_resp.data
        assert "Referer" not in cross_resp.data
