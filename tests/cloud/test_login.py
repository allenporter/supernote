"""Tests for the login flow."""

import hashlib

from aiohttp import web
import pytest_asyncio

from supernote.cloud.client import Client
from supernote.cloud.api_model import UserRandomCodeResponse, UserLoginResponse


# Mock SHA-256 implementation matching the JS one
def sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


async def handler_random_code(request: web.Request):
    """Handle random code request."""
    data = await request.json()
    if "account" not in data or "countryCode" not in data:
        return web.Response(status=400)
    return web.json_response(
        {"success": True, "randomCode": "123456", "timestamp": "1600000000"}
    )


async def handler_login_new(request: web.Request):
    """Handle new login request."""
    data = await request.json()
    # Verify password hash logic: SHA256(password + randomCode)
    # Assume password is "password" and randomCode is "123456"
    expected_hash = sha256("password" + "123456")

    if data.get("password") == expected_hash:
        return web.json_response({"success": True, "token": "new-access-token"})
    return web.json_response({"success": False, "errorMsg": "Invalid password"})


async def handler_csrf(request: web.Request):
    """Handle CSRF request."""
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


@pytest_asyncio.fixture(name="login_client")
async def client_fixture(aiohttp_client):
    app = web.Application()
    app.router.add_get("/csrf", handler_csrf)
    app.router.add_post("/official/user/query/random/code", handler_random_code)
    app.router.add_post("/official/user/account/login/new", handler_login_new)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))
    return Client(test_client.session, host=base_url.rstrip("/"))


async def test_login_flow(login_client):
    """Test the full login flow."""
    # Step 1: Get random code
    code_resp = await login_client.post_json(
        "official/user/query/random/code",
        UserRandomCodeResponse,
        json={"account": "test@example.com", "countryCode": 1},
    )
    assert code_resp.success
    assert code_resp.random_code == "123456"

    # Step 2: Calculate hash
    password = "password"
    password_hash = sha256(password + code_resp.random_code)

    # Step 3: Login
    login_resp = await login_client.post_json(
        "official/user/account/login/new",
        UserLoginResponse,
        json={
            "account": "test@example.com",
            "password": password_hash,
            "timestamp": code_resp.timestamp,
            "loginMethod": 1,
            "countryCode": 1,
            "equipment": 1,
            "browser": "Chrome",
            "language": "en",
        },
    )
    assert login_resp.success
    assert login_resp.token == "new-access-token"
