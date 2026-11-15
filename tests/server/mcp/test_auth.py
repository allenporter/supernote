"""Tests for MCP OAuth authorization server and login-bridge boundaries."""

import hashlib
import json

from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.testclient import TestClient

from supernote.models.user import UserRegisterDTO
from supernote.server.mcp.auth import SupernoteOAuthProvider, create_auth_app
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

        # Interactive session JWT passes auth check and reaches OAuth query validation (400)
        session_resp = client.post(
            "/login-bridge",
            headers={"Authorization": f"Bearer {session_jwt}"},
        )
        assert session_resp.status_code == 400
        assert session_resp.json() == {"error": "invalid_request"}


async def test_oauth_provider_migrates_legacy_email_tokens(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Verify SupernoteOAuthProvider loads legacy email user_id tokens as integer user_id."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="legacyoauth@example.com", password=pw_md5)
    )
    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    dummy_client = OAuthClientInformationFull(
        client_id="client_1",
        redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")],
    )

    await coordination_service.set_value(
        "mcp:refresh_token:rt_legacy",
        json.dumps(
            {
                "token": "rt_legacy",
                "user_id": "legacyoauth@example.com",
                "client_id": "client_1",
                "scopes": ["supernote:all"],
            }
        ),
    )
    loaded_rt = await provider.load_refresh_token(dummy_client, "rt_legacy")
    assert loaded_rt is not None
    assert loaded_rt.user_id == user.id

    await coordination_service.set_value(
        "mcp:access_token:at_legacy",
        json.dumps(
            {
                "token": "at_legacy",
                "user_id": "legacyoauth@example.com",
                "client_id": "client_1",
                "scopes": ["supernote:all"],
            }
        ),
    )
    loaded_at = await provider.load_access_token("at_legacy")
    assert loaded_at is not None
    assert loaded_at.user_id == user.id

    await coordination_service.set_value(
        "mcp:refresh_token:rt_unknown",
        json.dumps(
            {
                "token": "rt_unknown",
                "user_id": "missing@example.com",
                "client_id": "client_1",
                "scopes": ["supernote:all"],
            }
        ),
    )
    assert await provider.load_refresh_token(dummy_client, "rt_unknown") is None
    assert await provider.load_access_token("at_missing") is None
