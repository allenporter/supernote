"""Tests for MCP OAuth authorization server and login-bridge boundaries."""

import hashlib

from starlette.testclient import TestClient

from supernote.models.user import UserRegisterDTO
from supernote.server.mcp.auth import create_auth_app
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
