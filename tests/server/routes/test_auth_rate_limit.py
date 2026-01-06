import hashlib

import pytest

from supernote.client.client import Client
from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.utils.rate_limit import LIMIT_LOGIN_IP_MAX, LIMIT_PW_RESET_MAX


@pytest.mark.asyncio
async def test_login_rate_limit(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    # Setup
    account = "limit@example.com"
    pwd_hash = hashlib.md5(b"password").hexdigest()

    # URL
    url = "/api/official/user/account/login/new"

    # 1. First 20 attempts should succeed (or receive 401 if user doesn't exist, but pass rate limit)
    # The rate limiter is checked BEFORE login logic.
    # Current limit is 20 per IP per minute.

    # 1. First N attempts should succeed
    # The rate limiter is checked BEFORE login logic.

    for i in range(LIMIT_LOGIN_IP_MAX):
        # Use unique account to avoid hitting account limit (which is lower than IP limit)
        # We want to test IP limit here.
        unique_account = f"limit{i}@example.com"
        resp = await client.post(
            url,
            json={
                "account": unique_account,
                "password": pwd_hash,
                "equipmentNo": "TEST",
                "timestamp": "1234567890",
                "loginMethod": "1",
            },
        )
        if resp.status == 500:
            text = await resp.text()
            pytest.fail(f"Login failed with 500 on attempt {i + 1}: {text}")

        assert resp.status in [
            200,
            401,
        ]  # 401 because user might not exist, but NOT 429

    # LIMIT + 1 attempt should be 429
    resp = await client.post(
        url,
        json={
            "account": account,
            "password": pwd_hash,
            "equipmentNo": "TEST",
            "timestamp": "1234567890",
            "loginMethod": "1",
        },
    )
    assert resp.status == 429
    data = await resp.json()
    assert "Rate limit exceeded" in data["errorMsg"]


@pytest.mark.asyncio
async def test_password_retrieve_rate_limit(
    client: Client,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    # Enable remote password reset for this test
    # client.app is the aiohttp Application
    server_config.auth.enable_remote_password_reset = True

    # Setup
    account = "limit_reset@example.com"
    pwd_hash = hashlib.md5(b"password").hexdigest()

    # URL
    url = "/api/official/user/retrieve/password"

    # Limit is 5 per hour
    for i in range(LIMIT_PW_RESET_MAX):
        resp = await client.post(url, json={"email": account, "password": pwd_hash})
        if resp.status == 500:
            text = await resp.text()
            pytest.fail(f"Reset failed with 500 on attempt {i + 1}: {text}")
        assert resp.status in [200, 404]  # 404/200 OK

    # 6th attempt -> 429
    resp = await client.post(url, json={"email": account, "password": pwd_hash})
    assert resp.status == 429
