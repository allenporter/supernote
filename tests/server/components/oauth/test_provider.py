"""Tests for MCP OAuth authorization server and login-bridge boundaries."""

import hashlib
import time
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyHttpUrl, AnyUrl
from starlette.testclient import TestClient

from supernote.models.user import UserRegisterDTO
from supernote.server.components.oauth.http import create_auth_app
from supernote.server.components.oauth.models import (
    LoginBridgeDecision,
    LoginBridgeResponseVO,
    MCPScope,
    OAuthErrorResponseVO,
    SupernoteAuthorizationCode,
)
from supernote.server.components.oauth.provider import (
    SupernoteOAuthClientInformationFull,
    SupernoteOAuthProvider,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService


async def test_login_bridge_rejects_static_api_keys(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Verify static Bearer API keys cannot mint OAuth authorization codes via /login-bridge."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="bridgeuser@example.com", password=pw_md5)
    )
    raw_api_key, _ = await user_service.create_api_key(user.id, "Headless CLI")
    session_jwt = await user_service.create_session("bridgeuser@example.com")

    auth_app = create_auth_app(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )

    with TestClient(auth_app, base_url="http://localhost:8080") as client:
        # Unauthenticated POST returns 401
        unauth_resp = client.post("/login-bridge")
        assert unauth_resp.status_code == 401

        # Static API key via Authorization: Bearer or x-access-token is forbidden (403)
        bearer_resp = client.post(
            "/login-bridge",
            headers={"Authorization": f"Bearer {raw_api_key}"},
        )
        assert bearer_resp.status_code == 403
        assert bearer_resp.json() == {
            "error": "forbidden",
            "error_description": "API keys cannot authorize OAuth clients",
        }

        header_resp = client.get(
            "/login-bridge",
            headers={"x-access-token": raw_api_key},
        )
        assert header_resp.status_code == 403

        # OAuth 2.1 access tokens are also forbidden from authorizing new OAuth clients (403)
        existing_oauth_token, _ = await user_service.create_oauth_grant(
            user.id, "client_1", ["supernote:all"]
        )
        oauth_resp = client.post(
            "/login-bridge",
            headers={"Authorization": f"Bearer {existing_oauth_token}"},
        )
        assert oauth_resp.status_code == 403
        assert oauth_resp.json() == {
            "error": "forbidden",
            "error_description": "OAuth tokens cannot authorize OAuth clients",
        }

        # Interactive session JWT passes auth check and reaches OAuth query validation (400)
        session_resp = client.post(
            "/login-bridge",
            headers={"Authorization": f"Bearer {session_jwt}"},
        )
        assert session_resp.status_code == 400
        assert session_resp.json() == {"error": "invalid_request"}


async def test_oauth_provider_tokens_follow_their_grant(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Exchanged tokens load, refresh, and stop working once the grant is revoked."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="granted@example.com", password=pw_md5)
    )
    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    client = OAuthClientInformationFull(
        client_id="https://client.example.com/",
        redirect_uris=[AnyHttpUrl("https://client.example.com/")],
    )
    code = SupernoteAuthorizationCode(
        code="code_1",
        user_id=user.id,
        client_id=client.client_id,
        scopes=["supernote:all"],
        expires_at=time.time() + 600,
        code_challenge="challenge",
        redirect_uri=AnyUrl("https://client.example.com/"),
        redirect_uri_provided_explicitly=False,
    )
    await coordination_service.set_value("mcp:auth_code:code_1", code.model_dump_json())

    issued = await provider.exchange_authorization_code(client, code)
    assert issued.refresh_token is not None
    access = await provider.load_access_token(issued.access_token)
    assert access is not None
    assert (access.user_id, access.client_id, access.scopes, access.actor) == (
        user.id,
        client.client_id,
        ["supernote:all"],
        f"oauth:{client.client_id}",
    )
    refresh = await provider.load_refresh_token(client, issued.refresh_token)
    assert refresh is not None

    renewed = await provider.exchange_refresh_token(client, refresh, [])
    assert renewed.refresh_token == issued.refresh_token
    assert renewed.scope == "supernote:all"
    assert await provider.load_access_token(issued.access_token) is None
    assert await provider.load_access_token(renewed.access_token) is not None

    await provider.revoke_token(refresh)
    assert await provider.load_refresh_token(client, issued.refresh_token) is None
    assert await provider.load_access_token(renewed.access_token) is None
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(client, refresh, [])


async def test_authorize_and_login_bridge_consent_invariants(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Verify /authorize omits None params, GET /login-bridge always redirects to UI, and POST validates scopes."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="consent@example.com", password=pw_md5)
    )
    session_jwt = await user_service.create_session("consent@example.com")

    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    client_info = await provider.get_client("http://localhost:3000")
    assert client_info is not None

    bridge_url = await provider.authorize(
        client_info,
        AuthorizationParams(
            state=None,
            scopes=[MCPScope.ALL],
            code_challenge="pkce_challenge_123",
            redirect_uri=AnyUrl("http://localhost:3000"),
            redirect_uri_provided_explicitly=False,
            resource=None,
        ),
    )
    parsed_bridge = urlparse(bridge_url)
    bridge_qs = parse_qs(parsed_bridge.query)
    assert bridge_qs == {
        "client_id": ["http://localhost:3000"],
        "code_challenge": ["pkce_challenge_123"],
        "scope": [MCPScope.ALL],
    }

    auth_app = create_auth_app(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    bridge_path_qs = f"{parsed_bridge.path}?{parsed_bridge.query}"

    with TestClient(auth_app, base_url="http://localhost:8080") as client:
        # GET /login-bridge even with a valid session JWT redirects to SPA consent card
        # using an origin-relative return_to path so TLS-terminating reverse proxies work.
        get_resp = client.get(
            bridge_path_qs,
            headers={"x-access-token": session_jwt},
            follow_redirects=False,
        )
        assert get_resp.status_code == 302
        assert get_resp.headers["cache-control"] == "no-store"
        location = get_resp.headers["location"]
        assert location.startswith("/#login?return_to=")
        decoded_return_to = unquote(location.removeprefix("/#login?return_to="))
        assert decoded_return_to == bridge_path_qs

        # POST /login-bridge with decision=deny returns error=access_denied without minting a code
        deny_resp = client.post(
            f"{bridge_path_qs}&state=deny-st",
            json={"decision": LoginBridgeDecision.DENY},
            headers={"x-access-token": session_jwt},
        )
        assert deny_resp.status_code == 200
        assert deny_resp.headers["cache-control"] == "no-store"
        deny_vo = LoginBridgeResponseVO.from_json(deny_resp.text)
        deny_qs = parse_qs(urlparse(deny_vo.redirect_url).query)
        assert deny_qs == {"error": ["access_denied"], "state": ["deny-st"]}

        # POST /login-bridge with unknown decision enum or malformed JSON returns 400 invalid_request
        for bad_body in (b'{"decision": "maybe"}', b"{not-json"):
            bad_body_resp = client.post(
                bridge_path_qs,
                content=bad_body,
                headers={
                    "x-access-token": session_jwt,
                    "content-type": "application/json",
                },
            )
            assert bad_body_resp.status_code == 400
            assert bad_body_resp.headers["cache-control"] == "no-store"
            assert OAuthErrorResponseVO.from_json(
                bad_body_resp.text
            ) == OAuthErrorResponseVO(error="invalid_request")

        # POST /login-bridge with unsupported scope returns 400 invalid_scope
        bad_scope_resp = client.post(
            "/login-bridge",
            params={
                "client_id": "http://localhost:3000",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": "pkce_challenge_123",
                "scope": "unsupported:admin",
            },
            headers={"x-access-token": session_jwt},
        )
        assert bad_scope_resp.status_code == 400
        bad_scope_vo = OAuthErrorResponseVO.from_json(bad_scope_resp.text)
        assert bad_scope_vo.error == "invalid_scope"
        assert bad_scope_vo.error_description == "Requested scope is not supported."

        # POST /login-bridge with omitted redirect_uri resolves single registered URI
        # and records redirect_uri_provided_explicitly=False naturally.
        ok_resp = client.post(
            f"{bridge_path_qs}&resource=http%3A%2F%2Flocalhost%3A8081%2Fmcp",
            headers={"x-access-token": session_jwt},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.headers["cache-control"] == "no-store"
        redirect_url = ok_resp.json()["redirect_url"]
        cb_qs = parse_qs(urlparse(redirect_url).query)
        assert "state" not in cb_qs
        code_str = cb_qs["code"][0]

    stored = await provider.load_authorization_code(client_info, code_str)
    assert stored is not None
    assert stored.user_id == user.id
    assert stored.scopes == [MCPScope.ALL]
    assert stored.redirect_uri_provided_explicitly is False
    assert stored.resource == "http://localhost:8081/mcp"


@pytest.mark.parametrize(
    "bad_client_id",
    [
        "not-a-url",
        "http://localhost:99999",
        "http://user:pass@localhost:3000",
        "http://localhost:3000/app#frag",
        "http://localhost:3000/app/../evil",
        "http://localhost:3000/app/%2e%2e/evil",
    ],
)
async def test_get_client_rejects_malformed_or_unsafe_client_ids(
    user_service: UserService,
    coordination_service: CoordinationService,
    bad_client_id: str,
) -> None:
    """Verify get_client rejects malformed ports, userinfo, fragments, and dot-segments cleanly."""
    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    assert await provider.get_client(bad_client_id) is None


def test_validate_redirect_uri_default_and_custom_scheme_traversal() -> None:
    """Verify validate_redirect_uri resolves omitted single URI and blocks dot-segment traversal."""
    single_client = SupernoteOAuthClientInformationFull(
        client_id="obsidian://supernote-sync/app",
        redirect_uris=[AnyUrl("obsidian://supernote-sync/app")],
    )
    assert single_client.validate_redirect_uri(None) == AnyUrl(
        "obsidian://supernote-sync/app"
    )

    empty_client = SupernoteOAuthClientInformationFull(
        client_id="obsidian://supernote-sync",
        redirect_uris=[],
    )
    with pytest.raises(InvalidRedirectUriError):
        empty_client.validate_redirect_uri(None)

    for invalid_uri in (
        "obsidian://supernote-sync/app/%2e%2e/evil",
        "obsidian://supernote-sync/app%5c..%5cevil",
        "obsidian://supernote-sync/app#frag",
        "obsidian://user:pass@supernote-sync/app",
    ):
        with pytest.raises(InvalidRedirectUriError):
            single_client.validate_redirect_uri(AnyUrl(invalid_uri))
