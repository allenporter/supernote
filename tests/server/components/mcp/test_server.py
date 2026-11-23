"""Unit tests for `supernote.server.components.mcp.server`."""

from __future__ import annotations

import hashlib
from typing import Any

from starlette.testclient import TestClient

from supernote.models.user import UserRegisterDTO
from supernote.server.components.mcp import McpRegistrar
from supernote.server.components.mcp.server import (
    SupernoteTokenVerifier,
    create_mcp_server,
)
from supernote.server.services.user import UserService


async def test_token_verifier_static_key_session_and_oauth(
    user_service: UserService,
) -> None:
    """Test SupernoteTokenVerifier handles OAuth tokens, static API keys, and session JWTs."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcpuser@example.com", password=pw_md5)
    )
    verifier = SupernoteTokenVerifier(user_service)

    assert await verifier.verify_token("sn_invalid_token_1234567890abcdef") is None
    assert await verifier.verify_token("") is None
    assert await verifier.verify_token("x" * 5000) is None

    # Valid static Bearer API key
    raw_token, key_vo = await user_service.create_api_key(
        user.id, "Test Verifier", expires_at=2_000_000_000
    )
    result = await verifier.verify_token(raw_token)
    assert result is not None
    assert result.user_id == user.id
    assert result.scopes == ["supernote:all"]
    assert result.client_id == "api_key"
    assert result.expires_at == 2_000_000_000

    # Revoked static Bearer API key
    await user_service.revoke_api_key(user.id, key_vo.id)
    assert await verifier.verify_token(raw_token) is None

    # Session JWT token
    session_jwt = await user_service.create_session("mcpuser@example.com")
    session_result = await verifier.verify_token(session_jwt)
    assert session_result is not None
    assert session_result.user_id == user.id
    assert session_result.client_id == "session"
    assert session_result.scopes == ["supernote:all"]

    # OAuth access token, and its grant revoked
    oauth_token, _ = await user_service.create_oauth_grant(
        user.id, "oauth_client_1", ["supernote:all"]
    )
    oauth_result = await verifier.verify_token(oauth_token)
    assert oauth_result is not None
    assert oauth_result.user_id == user.id
    assert oauth_result.client_id == "oauth_client_1"
    assert oauth_result.scopes == ["supernote:all"]
    [grant] = await user_service.list_oauth_grants(user.id)
    await user_service.revoke_oauth_grant(user.id, grant.id)
    assert await verifier.verify_token(oauth_token) is None

    assert await verifier.verify_token("oauth_token_unknown") is None


async def test_mcp_http_requests_authenticate_and_succeed(
    user_service: UserService,
) -> None:
    """Test MCP Streamable HTTP transport authentication with static Bearer keys."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcphttp@example.com", password=pw_md5)
    )
    raw_token, key_vo = await user_service.create_api_key(user.id, "MCP Key")

    mcp = create_mcp_server(
        issuer_url="http://localhost:8080",
        resource_server_url="http://localhost:8080/mcp",
        user_service=user_service,
    )
    registrar = McpRegistrar()

    async def ping() -> dict[str, Any]:
        return {"success": True, "pong": True}

    registrar.add_tool(ping)
    registrar.apply_to_server(mcp)

    app = mcp.streamable_http_app()

    with TestClient(app, base_url="http://localhost:8080") as client:
        unauth_resp = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        assert unauth_resp.status_code == 401

        invalid_resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Authorization": "Bearer sn_invalidtoken1234567890abcdef0123"},
        )
        assert invalid_resp.status_code == 401

        init_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        init_resp = client.post(
            "/mcp",
            json=init_body,
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert init_resp.status_code == 200
        session_id = init_resp.headers.get("mcp-session-id")

        headers = {"Authorization": f"Bearer {raw_token}"}
        if session_id:
            headers["mcp-session-id"] = session_id

        tool_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "ping", "arguments": {}},
            },
            headers=headers,
        )
        assert tool_resp.status_code == 200
        assert "pong" in tool_resp.text

        await user_service.revoke_api_key(user.id, key_vo.id)
        revoked_resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "initialize"},
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert revoked_resp.status_code == 401


async def test_token_verifier_sets_canonical_actor_for_oauth_and_api_keys(
    user_service: UserService,
) -> None:
    """Verify SupernoteTokenVerifier sets canonical `oauth:` and `api_key:` actor IDs."""
    user = await user_service.register(
        UserRegisterDTO(
            email="actor-test@example.com",
            password=hashlib.md5(b"password").hexdigest(),
            user_name="Actor Test",
        )
    )
    verifier = SupernoteTokenVerifier(user_service)

    oauth_token, _ = await user_service.create_oauth_grant(
        user.id, "   ", ["supernote:all"]
    )
    oauth_tok = await verifier.verify_token(oauth_token)
    assert oauth_tok is not None
    assert oauth_tok.actor == "oauth:unknown"

    raw_key, key_vo = await user_service.create_api_key(user.id, "agent")
    api_tok = await verifier.verify_token(raw_key)
    assert api_tok is not None
    assert api_tok.actor == f"api_key:{key_vo.id}"
