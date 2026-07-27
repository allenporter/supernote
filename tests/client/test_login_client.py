"""Tests for supernote.client.login_client module."""

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import Client
from supernote.client.exceptions import ApiException, SmsVerificationRequired
from supernote.client.hashing import hash_password
from supernote.client.login_client import LoginClient
from supernote.models.auth import LoginVO


async def handler_csrf(request: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


async def test_login_client_flow(aiohttp_client: AiohttpClient) -> None:
    """Test standard login flow in LoginClient."""
    calls = []

    async def handler_query_token(request: web.Request) -> web.Response:
        calls.append("query_token")
        return web.json_response({"success": True})

    async def handler_random_code(request: web.Request) -> web.Response:
        data = await request.json()
        calls.append(("random_code", data))
        return web.json_response(
            {"success": True, "randomCode": "salt123", "timestamp": "1600000000"}
        )

    async def handler_login_new(request: web.Request) -> web.Response:
        data = await request.json()
        calls.append(("login_new", data))
        return web.json_response(
            {"success": True, "token": "user-access-token-123", "counts": "0"}
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/query/token", handler_query_token)
    app.router.add_post("/api/official/user/query/random/code", handler_random_code)
    app.router.add_post("/api/official/user/account/login/new", handler_login_new)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    login_client = LoginClient(client)

    token = await login_client.login("user@example.com", "mypassword")
    assert token == "user-access-token-123"
    assert calls[0] == "query_token"
    assert calls[1][0] == "random_code"
    assert calls[2][0] == "login_new"
    assert calls[2][1]["account"] == "user@example.com"
    assert calls[2][1]["password"] == hash_password("mypassword", "salt123")


async def test_login_client_equipment_email_and_phone(
    aiohttp_client: AiohttpClient,
) -> None:
    """Test login_equipment for both email and phone accounts."""
    recorded_logins = []

    async def handler_query_token(request: web.Request) -> web.Response:
        return web.json_response({"success": True})

    async def handler_random_code(request: web.Request) -> web.Response:
        return web.json_response(
            {"success": True, "randomCode": "salt123", "timestamp": "1600000000"}
        )

    async def handler_login_equipment(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_logins.append(data)
        return web.json_response(
            {"success": True, "token": "eq-token-456", "counts": "0"}
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/query/token", handler_query_token)
    app.router.add_post("/api/official/user/query/random/code", handler_random_code)
    app.router.add_post(
        "/api/official/user/account/login/equipment", handler_login_equipment
    )

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    login_client = LoginClient(client)

    # 1. Email login equipment
    res1 = await login_client.login_equipment("user@example.com", "pass123", "EQ001")
    assert isinstance(res1, LoginVO)
    assert res1.token == "eq-token-456"
    assert recorded_logins[-1]["loginMethod"] in (2, "2")

    # 2. Phone login equipment
    res2 = await login_client.login_equipment("1234567890", "pass123", "EQ002")
    assert isinstance(res2, LoginVO)
    assert recorded_logins[-1]["loginMethod"] in (1, "1")
    assert recorded_logins[-1]["equipmentNo"] == "EQ002"


async def test_login_sms_verification_required_and_retry(
    aiohttp_client: AiohttpClient,
) -> None:
    """Test login when SMS verification code is required and handling login retries."""
    attempts = 0

    async def handler_query_token(request: web.Request) -> web.Response:
        return web.json_response({"success": True})

    async def handler_random_code(request: web.Request) -> web.Response:
        return web.json_response(
            {"success": True, "randomCode": "salt123", "timestamp": "1600000000"}
        )

    async def handler_login_new(request: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.json_response(
                {"success": False, "errorMsg": "Please enter verification code"}
            )
        return web.json_response(
            {"success": True, "token": "retry-token-789", "counts": "0"}
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/query/token", handler_query_token)
    app.router.add_post("/api/official/user/query/random/code", handler_random_code)
    app.router.add_post("/api/official/user/account/login/new", handler_login_new)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    login_client = LoginClient(client)

    # Attempt 1: raises SmsVerificationRequired
    with pytest.raises(SmsVerificationRequired) as exc_info:
        await login_client.login("user@example.com", "pass123")
    assert "verification code" in str(exc_info.value)
    assert exc_info.value.timestamp == "1600000000"

    # Retry attempt: succeeds
    token = await login_client.login("user@example.com", "pass123")
    assert token == "retry-token-789"
    assert attempts == 2


async def test_login_general_api_exception(aiohttp_client: AiohttpClient) -> None:
    """Test login when general API error occurs."""

    async def handler_query_token(request: web.Request) -> web.Response:
        return web.json_response({"success": True})

    async def handler_random_code(request: web.Request) -> web.Response:
        return web.json_response(
            {"success": True, "randomCode": "salt123", "timestamp": "1600000000"}
        )

    async def handler_login_new(request: web.Request) -> web.Response:
        return web.json_response({"success": False, "errorMsg": "Invalid credentials"})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/query/token", handler_query_token)
    app.router.add_post("/api/official/user/query/random/code", handler_random_code)
    app.router.add_post("/api/official/user/account/login/new", handler_login_new)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    login_client = LoginClient(client)

    with pytest.raises(ApiException, match="Invalid credentials"):
        await login_client.login("user@example.com", "wrongpass")


async def test_sms_login_and_request_code(aiohttp_client: AiohttpClient) -> None:
    """Test sms_login and request_sms_code methods."""
    recorded_calls = []

    async def handler_sms_login(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_calls.append(("sms_login", data))
        return web.json_response({"success": True, "token": "sms-auth-token"})

    async def handler_pre_auth(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_calls.append(("pre_auth", data))
        return web.json_response({"success": True, "token": "tok-saltpart-1"})

    async def handler_random_code(request: web.Request) -> web.Response:
        return web.json_response(
            {"success": True, "randomCode": "code123", "timestamp": "1700000000"}
        )

    async def handler_send_sms(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_calls.append(("send_sms", data))
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/official/user/sms/login", handler_sms_login)
    app.router.add_post("/api/user/validcode/pre-auth", handler_pre_auth)
    app.router.add_post("/api/official/user/query/random/code", handler_random_code)
    app.router.add_post("/api/user/sms/validcode/send", handler_send_sms)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    client = Client(test_client.session, host=base_url)
    login_client = LoginClient(client)

    # 1. sms_login
    token = await login_client.sms_login("1234567890", "9999", "1600000000")
    assert token == "sms-auth-token"
    assert recorded_calls[0][0] == "sms_login"
    assert recorded_calls[0][1]["telephone"] == "1234567890"
    assert recorded_calls[0][1]["validCode"] == "9999"

    # 2. request_sms_code
    await login_client.request_sms_code("1234567890", country_code=1)
    assert recorded_calls[1][0] == "pre_auth"
    assert recorded_calls[1][1]["account"] == "11234567890"
    assert recorded_calls[2][0] == "send_sms"
    assert recorded_calls[2][1]["telephone"] == "1234567890"
    assert recorded_calls[2][1]["nationcode"] == 1
    assert recorded_calls[2][1]["token"] == "tok-saltpart-1"
