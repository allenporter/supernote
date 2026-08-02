import base64
import hashlib

import pytest
import yarl
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.login_client import LoginClient
from tests.server.conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture(name="login_client")
async def supernote_login_client_fixture(client: TestClient) -> LoginClient:
    base_url = str(client.make_url("/"))
    real_client = Client(client.session, host=base_url)
    return LoginClient(real_client)


def calculate_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def test_scenario_oauth_cold_login(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """
    Scenario 1: Cold Start (Not Logged In) - Complete Flow
    1. User clicks 'Login with Supernote' and is redirected to Bridge -> Login Page.
    2. User performs actual login via API.
    3. Frontend 'Resumes Session' with new token.
    4. Code exchange completes successfully.
    """
    # 1. Authorize -> Bridge -> Login Page
    verifier = "v" * 50
    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    resp1 = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": "cold-state",
            "scope": "supernote:all",
            "code_challenge": calculate_s256(verifier),
            "code_challenge_method": "S256",
        },
        allow_redirects=False,
    )
    assert resp1.status in (302, 307)
    bridge_path = yarl.URL(resp1.headers["Location"]).path_qs

    resp2 = await client.get(bridge_path, allow_redirects=False)
    assert resp2.status in (302, 307)
    assert "/#login" in resp2.headers["Location"]
    assert "return_to" in resp2.headers["Location"]

    # 2. Real User Login
    fresh_token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)
    assert fresh_token

    # 3. Resume Session (POST to Bridge)
    resp3 = await client.post(
        bridge_path,
        headers={"x-access-token": fresh_token},
        allow_redirects=False,
    )
    assert resp3.status == 200
    callback_url = (await resp3.json())["redirect_url"]

    # 4. Token Exchange
    code = yarl.URL(callback_url).query["code"]
    token_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert token_resp.status == 200
    assert "access_token" in await token_resp.json()


async def test_scenario_oauth_warm_session(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """
    Scenario 2: Warm Session (Already Logged In)
    1. User is already logged in (simulated by having a token).
    2. User triggers OAuth flow.
    3. Frontend fast-forwards through bridge using existing token.
    """
    # 1. Warm up session
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)

    # 2. Authorize
    verifier = "v" * 50
    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    resp1 = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": "warm-state",
            "code_challenge": calculate_s256(verifier),
            "code_challenge_method": "S256",
        },
        allow_redirects=False,
    )
    bridge_path = yarl.URL(resp1.headers["Location"]).path_qs

    # 3. Bridge Fast-Forward
    resp2 = await client.post(
        bridge_path,
        headers={"x-access-token": token},
        allow_redirects=False,
    )
    assert resp2.status == 200
    callback_url = (await resp2.json())["redirect_url"]

    # 4. Exchange
    code = yarl.URL(callback_url).query["code"]
    token_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert token_resp.status == 200


async def test_scenario_security_edge_cases(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """
    Scenario 3: Security & Error Handling
    1. Invalid Token handling on Bridge (POST vs GET).
    2. IndieAuth validation (Valid vs Mismatch).
    """
    # Setup
    params = {
        "client_id": "http://localhost:3000",
        "redirect_uri": "http://localhost:3000/callback",
    }

    # 1a. POST with Invalid Token -> 401 Unauthorized (API Mode)
    resp_invalid = await client.post(
        "/login-bridge",
        params=params,
        headers={"x-access-token": "bad-token"},
    )
    assert resp_invalid.status == 401

    # 1b. GET with Invalid Token -> Redirect to Login (Browser Mode)
    resp_redirect = await client.get(
        "/login-bridge",
        params=params,
        headers={"x-access-token": "bad-token"},
        allow_redirects=False,
    )
    assert resp_redirect.status in (302, 307)
    assert "/#login" in resp_redirect.headers["Location"]

    # 2a. IndieAuth Valid (client_id matches redirect_uri host)
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)
    resp_indie = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "http://localhost:5000",
            "redirect_uri": "http://localhost:5000/callback",
            "code_challenge": "mock",
            "code_challenge_method": "S256",
        },
        allow_redirects=False,
    )
    bridge_path = yarl.URL(resp_indie.headers["Location"]).path_qs

    resp_indie_bridge = await client.post(
        bridge_path,
        headers={"x-access-token": token},
    )
    assert resp_indie_bridge.status == 200
    assert "localhost:5000/callback" in (await resp_indie_bridge.json())["redirect_url"]

    # 2b. IndieAuth Mismatch
    resp_mismatch = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "http://localhost:3000",
            "redirect_uri": "http://evil.com/callback",
            "code_challenge": "mock",
            "code_challenge_method": "S256",
        },
        allow_redirects=True,
    )
    assert resp_mismatch.status == 400
