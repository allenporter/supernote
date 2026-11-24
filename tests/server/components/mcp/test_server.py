"""Unit tests for `supernote.server.components.mcp.server`."""

from __future__ import annotations

import hashlib

import httpx2
import pytest

from supernote.models.user import UserRegisterDTO
from supernote.server.components.mcp.server import SupernoteTokenVerifier
from supernote.server.services.user import UserService
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


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
    mcp_url: str,
    auth_headers: dict[str, str],
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Test MCP Streamable HTTP transport authentication with API keys and sessions."""
    async with httpx2.AsyncClient() as http_client:
        unauth_resp = await http_client.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert unauth_resp.status_code == 401

        invalid_resp = await http_client.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer sn_invalidtoken1234567890abcdef0123",
            },
        )
        assert invalid_resp.status_code == 401

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert "list_tasks" in {t.name for t in tools.tools}
        session_result = await call_mcp_tool(session, "list_tasks")
        assert session_result["success"] is True

    raw_token, key_vo = await user_service.create_api_key(test_user_id, "MCP Key")
    async with mcp_session(mcp_url, {"x-access-token": raw_token}) as session:
        api_key_result = await call_mcp_tool(session, "list_tasks")
        assert api_key_result["success"] is True

    await user_service.revoke_api_key(test_user_id, key_vo.id)
    async with httpx2.AsyncClient() as http_client:
        revoked_resp = await http_client.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": 3, "method": "initialize"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {raw_token}",
            },
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
