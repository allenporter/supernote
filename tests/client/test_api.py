"""Tests for the Supernote session API."""

import aiohttp
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import ConstantAuth, Supernote
from supernote.client.device import DeviceClient
from supernote.client.web import WebClient
from supernote.models.auth import UserQueryByIdVO


async def test_supernote_init() -> None:
    """Test Supernote session initialization."""
    async with aiohttp.ClientSession() as session:
        sn = Supernote(host="http://test", session=session)
        assert sn._client.host == "http://test"
        assert isinstance(sn.web, WebClient)
        assert isinstance(sn.device, DeviceClient)
        assert sn._session == session


async def test_supernote_with_token() -> None:
    """Test Supernote with a token."""
    sn = Supernote.from_token("test-token", host="http://test")
    assert sn.token == "test-token"
    assert isinstance(sn._client.get_auth(), ConstantAuth)


async def test_supernote_immutability() -> None:
    """Test that Supernote objects are immutable."""
    sn1 = Supernote(host="http://test")
    auth = ConstantAuth("token1")
    sn2 = sn1.with_auth(auth)

    assert sn1.token is None
    assert sn2.token == "token1"
    assert sn1 is not sn2


async def test_supernote_context_manager() -> None:
    """Test Supernote as a context manager."""
    # Test with internal session management
    sn = Supernote(host="http://test")
    session = sn._session
    assert not session.closed
    async with sn:
        pass
    assert session.closed


async def test_supernote_external_session() -> None:
    """Test Supernote with external session management."""
    async with aiohttp.ClientSession() as session:
        sn = Supernote(session=session, host="http://test")
        async with sn:
            pass
        assert not session.closed


async def test_query_user_success(
    aiohttp_client: AiohttpClient,
) -> None:
    """Test successful user query."""

    async def handler_csrf(request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})

    async def handler_query_user(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "success": True,
                "user": {
                    "userName": "test-user",
                    "email": "test@example.com",
                    "totalCapacity": "100",
                },
                "isUser": True,
            }
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/query", handler_query_user)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    async with Supernote.from_token(
        "test-token", host=base_url, session=test_client.session
    ) as sn:
        user_resp = await sn.web.query_user()
        assert isinstance(user_resp, UserQueryByIdVO)
        assert user_resp.success
        assert user_resp.user is not None
        assert user_resp.user.user_name == "test-user"
