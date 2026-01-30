import base64
import hashlib

import yarl
from aiohttp.test_utils import TestClient

from supernote.server.config import ServerConfig


def calculate_s256(verifier: str) -> str:
    """Calculate S256 code challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def test_oauth_full_flow(
    client: TestClient, server_config: ServerConfig, auth_headers: dict[str, str]
) -> None:
    """Test the full OAuth flow from authorize to token exchange."""

    # 1. Authorize - should redirect to login-bridge
    # Verifier must be 43-128 chars
    verifier = "v" * 50
    # Calculate S256 challenge
    challenge = calculate_s256(verifier)

    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": "test-state",
        "scope": "supernote:all",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    token = auth_headers["x-access-token"]
    # Sync aiohttp TestClient cookie jar with session token
    client.session.cookie_jar.update_cookies({"session": token})

    # GET /authorize
    # Handler will redirect to login-bridge
    resp1 = await client.get("/authorize", params=params, allow_redirects=False)

    # Authorize Status Check
    print(f"Authorize Status: {resp1.status}")
    if resp1.status not in (302, 307):
        print(f"Authorize Body: {await resp1.text()}")
    assert resp1.status in (302, 307)
    assert "login-bridge" in resp1.headers["Location"]

    # Follow to login-bridge using relative URL
    login_bridge_url = resp1.headers["Location"]
    print(f"Login Bridge URL: {login_bridge_url}")
    relative_bridge_url = yarl.URL(login_bridge_url).path_qs
    resp2 = await client.get(relative_bridge_url, allow_redirects=False)

    # Bridge Status Check
    print(f"Bridge Status: {resp2.status}")
    if resp2.status not in (302, 307):
        print(f"Bridge Body: {await resp2.text()}")
    assert resp2.status in (302, 307)

    # This should be the callback URL
    callback_url = resp2.headers["Location"]
    assert "localhost:3000/callback" in callback_url
    assert "code=" in callback_url
    assert "state=test-state" in callback_url

    final_url = yarl.URL(callback_url)
    code = final_url.query.get("code")
    assert code

    # 2. Token Exchange
    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }

    token_resp = await client.post("/token", data=token_params)
    assert token_resp.status == 200, f"Token exchange failed: {await token_resp.text()}"
    token_data = await token_resp.json()
    assert "access_token" in token_data
    assert "refresh_token" in token_data
    assert token_data["token_type"] == "Bearer"


async def test_oauth_unauthenticated_redirect(client: TestClient) -> None:
    """Test that authorize redirects to login if no session is present."""
    # Verifier must be 43-128 chars
    verifier = "v" * 50
    challenge = calculate_s256(verifier)

    client_id = "http://localhost:3000"
    redirect_uri = "http://localhost:3000/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "supernote:all",
        "state": "test",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    # should NOT follow redirects automatically to see the first redirect destination
    resp = await client.get("/authorize", params=params, allow_redirects=False)

    # authorize -> login-bridge (internal to SDK/AS)
    assert resp.status in (302, 307)
    assert "login-bridge" in resp.headers["Location"]

    # Verify login-bridge -> login page using relative URL
    login_bridge_url = resp.headers["Location"]
    relative_bridge_url = yarl.URL(login_bridge_url).path_qs
    resp2 = await client.get(relative_bridge_url, allow_redirects=False)

    assert resp2.status in (302, 307)
    # Checks that we are redirected to the login page (hash based router for frontend)
    assert "#login" in resp2.headers["Location"]
    # Check return_to param
    location = resp2.headers["Location"]
    assert "return_to" in location


async def test_indieauth_valid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test IndieAuth style: valid URL client_id matching redirect_uri."""

    # client_id is a URL
    client_id = "http://localhost:5000"
    # Same host
    redirect_uri = "http://localhost:5000/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": "test",
        "scope": "supernote:all",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }

    token = auth_headers["x-access-token"]
    client.session.cookie_jar.update_cookies({"session": token})

    resp = await client.get("/authorize", params=params, allow_redirects=False)
    # authorize -> login-bridge
    assert resp.status in (302, 307)
    login_bridge_url = resp.headers["Location"]
    relative_bridge_url = yarl.URL(login_bridge_url).path_qs

    # login-bridge -> callback (success)
    resp2 = await client.get(relative_bridge_url, allow_redirects=False)
    assert resp2.status in (302, 307)
    assert "code=" in resp2.headers["Location"]
    assert "localhost:5000/callback" in resp2.headers["Location"]


async def test_indieauth_mismatch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test IndieAuth style: valid URL client_id but mismatched redirect_uri."""

    client_id = "http://localhost:3000"
    redirect_uri = "http://evil.com/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": "test",
        "scope": "supernote:all",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }

    token = auth_headers["x-access-token"]
    client.session.cookie_jar.update_cookies({"session": token})

    # Redirects not allowed because we expect an error page or error JSON (actually JSONResponse 400)
    resp = await client.get("/authorize", params=params, allow_redirects=True)
    assert resp.status == 400
    text = await resp.text()
    assert "Redirect URI 'http://evil.com/callback' not in allowed list" in text
