import base64
import hashlib

import pytest
import yarl
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.login_client import LoginClient
from supernote.server.keys import COORDINATION_SERVICE_KEY
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


async def test_login_bridge_rejects_mismatched_redirect_uri(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Verify /login-bridge directly validates redirect_uri against client_id before issuing an auth code."""
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)

    resp = await client.post(
        "/login-bridge",
        params={
            "client_id": "http://localhost:3000",
            "redirect_uri": "http://evil.com/callback",
            "code_challenge": "challenge123",
        },
        headers={"x-access-token": token},
    )
    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "invalid_redirect_uri"


async def test_login_bridge_rejects_prefix_spoofing_and_traversal(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Verify validate_redirect_uri blocks authority prefix spoofing, path sibling prefix spoofing, and '..' traversal."""
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)

    for bad_redirect in (
        "http://localhost:3000.evil.com/app/cb",
        "http://localhost:3000/app-evil/cb",
        "http://localhost:3000/app/../evil",
    ):
        resp = await client.post(
            "/login-bridge",
            params={
                "client_id": "http://localhost:3000/app",
                "redirect_uri": bad_redirect,
                "code_challenge": "challenge123",
            },
            headers={"x-access-token": token},
        )
        assert resp.status == 400, f"Expected 400 for {bad_redirect}"


async def test_login_bridge_requires_code_challenge(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Verify /login-bridge rejects requests missing a PKCE code_challenge."""
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)

    resp = await client.post(
        "/login-bridge",
        params={
            "client_id": "http://localhost:3000",
            "redirect_uri": "http://localhost:3000/callback",
        },
        headers={"x-access-token": token},
    )
    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "invalid_request"


async def test_authorization_code_single_use_prevents_replay(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Verify an authorization code can only be exchanged once."""
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)
    verifier = "v" * 50
    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    bridge_resp = await client.post(
        "/login-bridge",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": calculate_s256(verifier),
        },
        headers={"x-access-token": token},
    )
    assert bridge_resp.status == 200
    callback_url = (await bridge_resp.json())["redirect_url"]
    code = yarl.URL(callback_url).query["code"]

    first_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert first_resp.status == 200

    replay_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert replay_resp.status == 400
    replay_body = await replay_resp.json()
    assert replay_body["error"] == "invalid_grant"


async def test_oauth_token_revocation(
    client: TestClient,
    login_client: LoginClient,
    create_test_user: None,
) -> None:
    """Verify /revoke invalidates both access and refresh tokens in CoordinationService."""
    token = await login_client.login(TEST_USERNAME, TEST_PASSWORD)
    verifier = "v" * 50
    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    bridge_resp = await client.post(
        "/login-bridge",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": calculate_s256(verifier),
        },
        headers={"x-access-token": token},
    )
    code = yarl.URL((await bridge_resp.json())["redirect_url"]).query["code"]

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
    tokens = await token_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    coordination = client.app[COORDINATION_SERVICE_KEY]
    assert await coordination.get_value(f"mcp:access_token:{access_token}") is not None
    assert (
        await coordination.get_value(f"mcp:refresh_token:{refresh_token}") is not None
    )

    revoke_access_resp = await client.post(
        "/revoke",
        data={"token": access_token, "client_id": client_id, "client_secret": ""},
    )
    assert revoke_access_resp.status == 200
    assert await coordination.get_value(f"mcp:access_token:{access_token}") is None

    revoke_refresh_resp = await client.post(
        "/revoke",
        data={
            "token": refresh_token,
            "token_type_hint": "refresh_token",
            "client_id": client_id,
            "client_secret": "",
        },
    )
    assert revoke_refresh_resp.status == 200
    assert await coordination.get_value(f"mcp:refresh_token:{refresh_token}") is None

    refresh_attempt = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )
    assert refresh_attempt.status == 400
    assert (await refresh_attempt.json())["error"] == "invalid_grant"
