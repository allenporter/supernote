"""Unit and integration tests for MCP server authentication and endpoints."""

import hashlib
import json
from unittest.mock import AsyncMock

from mcp.server.auth.middleware.auth_context import (
    AuthenticatedUser,
    auth_context_var,
)
from mcp.server.mcpserver import Context
from starlette.testclient import TestClient

from supernote.models.user import UserRegisterDTO
from supernote.server.mcp.models import SupernoteAccessToken
from supernote.server.mcp.server import (
    SupernoteTokenVerifier,
    _get_auth_user_id,
    create_mcp_server,
    set_services,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.search import SearchService
from supernote.server.services.user import UserService


async def test_token_verifier_static_key_session_and_oauth(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Test SupernoteTokenVerifier handles OAuth tokens, static API keys, and session JWTs."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcpuser@example.com", password=pw_md5)
    )
    verifier = SupernoteTokenVerifier(user_service, coordination_service)

    assert await verifier.verify_token("sn_invalid_token_1234567890abcdef") is None

    # Valid static Bearer API key
    raw_token, key_vo = await user_service.create_api_key(user.id, "Test Verifier")
    result = await verifier.verify_token(raw_token)
    assert result is not None
    assert result.user_id == "mcpuser@example.com"
    assert result.scopes == ["supernote:all"]
    assert result.client_id == "api_key"

    # Revoked static Bearer API key
    await user_service.revoke_api_key(user.id, key_vo.id)
    assert await verifier.verify_token(raw_token) is None

    # Session JWT token
    session_jwt = await user_service.create_session("mcpuser@example.com")
    session_result = await verifier.verify_token(session_jwt)
    assert session_result is not None
    assert session_result.user_id == "mcpuser@example.com"
    assert session_result.client_id == "session"
    assert session_result.scopes == ["supernote:all"]

    # OAuth access token
    oauth_token = "oauth_token_xyz"
    oauth_data = {
        "user_id": "mcpuser@example.com",
        "client_id": "oauth_client_1",
        "scopes": ["supernote:all"],
    }
    await coordination_service.set_value(
        f"mcp:access_token:{oauth_token}", json.dumps(oauth_data)
    )

    oauth_result = await verifier.verify_token(oauth_token)
    assert oauth_result is not None
    assert oauth_result.user_id == "mcpuser@example.com"
    assert oauth_result.client_id == "oauth_client_1"
    assert oauth_result.scopes == ["supernote:all"]

    assert await verifier.verify_token("oauth_token_unknown") is None


async def test_get_auth_user_id() -> None:
    """Test _get_auth_user_id resolves numeric IDs, emails, and handles missing users."""
    mock_user_service = AsyncMock(spec=UserService)
    mock_user_service.get_user_id.side_effect = lambda acc: (
        10
        if acc == "user@example.com"
        else (_ for _ in ()).throw(ValueError(f"User {acc} not found"))
    )
    mock_search = AsyncMock(spec=SearchService)
    mock_coord = AsyncMock(spec=CoordinationService)
    set_services(mock_search, mock_user_service, mock_coord)

    ctx = AsyncMock(spec=Context)

    assert await _get_auth_user_id(ctx) is None

    token_numeric = SupernoteAccessToken(
        token="tok1", user_id="42", client_id="c1", scopes=["supernote:all"]
    )
    tok = auth_context_var.set(AuthenticatedUser(token_numeric))
    try:
        assert await _get_auth_user_id(ctx) == 42
    finally:
        auth_context_var.reset(tok)

    token_email = SupernoteAccessToken(
        token="tok2",
        user_id="user@example.com",
        client_id="c1",
        scopes=["supernote:all"],
    )
    tok = auth_context_var.set(AuthenticatedUser(token_email))
    try:
        assert await _get_auth_user_id(ctx) == 10
    finally:
        auth_context_var.reset(tok)

    token_unknown = SupernoteAccessToken(
        token="tok3",
        user_id="unknown@example.com",
        client_id="c1",
        scopes=["supernote:all"],
    )
    tok = auth_context_var.set(AuthenticatedUser(token_unknown))
    try:
        assert await _get_auth_user_id(ctx) is None
    finally:
        auth_context_var.reset(tok)


async def test_mcp_http_requests_authenticate_and_succeed(
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Test MCP Streamable HTTP transport authentication with static Bearer keys."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="mcphttp@example.com", password=pw_md5)
    )
    mock_search_service = AsyncMock(spec=SearchService)
    mock_search_service.list_notebooks.return_value = []
    set_services(mock_search_service, user_service, coordination_service)

    raw_token, key_vo = await user_service.create_api_key(user.id, "MCP Key")

    mcp = create_mcp_server(
        issuer_url="http://localhost:8080",
        resource_server_url="http://localhost:8080/mcp",
    )
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
                "params": {"name": "list_notebooks", "arguments": {}},
            },
            headers=headers,
        )
        assert tool_resp.status_code == 200
        assert "notebooks" in tool_resp.text

        await user_service.revoke_api_key(user.id, key_vo.id)
        revoked_resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "initialize"},
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert revoked_resp.status_code == 401
