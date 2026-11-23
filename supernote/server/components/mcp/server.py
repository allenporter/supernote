"""Streamable HTTP Model Context Protocol (MCP) Resource Server host.

Defines `create_mcp_server`, `run_server`, and `SupernoteTokenVerifier`.
Domain tools are registered dynamically onto the `MCPServer` via
`supernote.server.components.mcp.McpRegistrar` by components declaring
``platforms = ("mcp",)`` (such as `search`, `transcript`, and `schedule`).

Validates both OAuth 2.1 Bearer tokens issued by
`supernote.server.components.oauth.provider.SupernoteOAuthProvider` and static
Bearer API keys (`sn_...`) via `supernote.server.services.user.UserService`.
See `supernote.guides.mcp`.
"""

from __future__ import annotations

import logging

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from supernote.server.components.oauth.models import (
    MCPScope,
    SupernoteAccessToken,
)
from supernote.server.services.user import AuthMethod, UserService

__all__ = [
    "MAX_MCP_TOKEN_LENGTH",
    "SupernoteTokenVerifier",
    "create_mcp_server",
    "run_server",
]

logger = logging.getLogger(__name__)
MAX_MCP_TOKEN_LENGTH = 4096


class SupernoteTokenVerifier(TokenVerifier):
    """Verifier that maps bearer tokens to users using `UserService`."""

    def __init__(self, user_service: UserService) -> None:
        self.user_service = user_service

    async def verify_token(self, token: str) -> SupernoteAccessToken | None:
        if not token or len(token) > MAX_MCP_TOKEN_LENGTH:
            return None
        if not (session := await self.user_service.verify_token(token)):
            return None

        if session.auth_method == AuthMethod.OAUTH:
            client_id = session.actor_id or "unknown"
            scopes = list(session.scopes)
        else:
            client_id = "api_key" if session.is_api_key else "session"
            scopes = [MCPScope.ALL]

        return SupernoteAccessToken(
            token=token,
            user_id=session.user_id,
            client_id=client_id,
            scopes=scopes,
            resource=session.resource,
            expires_at=session.expires_at,
            actor=session.actor,
        )


def create_mcp_server(
    issuer_url: str,
    resource_server_url: str,
    user_service: UserService,
) -> MCPServer:
    """Create a new `MCPServer` instance backed by `SupernoteTokenVerifier`."""
    token_verifier = SupernoteTokenVerifier(user_service)
    return MCPServer(
        "Supernote Retrieval",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_server_url),
            required_scopes=[MCPScope.ALL],
            # SupernoteTokenVerifier validates opaque tokens stored in the
            # server-local mcp:access_token:* namespace exclusively for this
            # embedded MCP resource server.
            validate_token_resource=False,
        ),
        token_verifier=token_verifier,
    )


async def run_server(
    mcp: MCPServer, host: str, port: int, proxy_mode: str | None = None
) -> None:
    """Run the `MCPServer` with Streamable HTTP transport."""
    transport_security: TransportSecuritySettings | None = None
    # Relax security for custom host headers (e.g. k8s ingress) only if proxy mode is enabled.
    # This prevents DNS rebinding attacks while allowing operation behind proxies.
    if proxy_mode == "relaxed":
        logger.info(
            f"Proxy mode {proxy_mode} detected. Relaxing MCP transport security."
        )
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    logger.info(f"Starting MCP server on {host}:{port} using streamable-http...")
    await mcp.run_streamable_http_async(
        host=host,
        port=port,
        transport_security=transport_security,
    )
