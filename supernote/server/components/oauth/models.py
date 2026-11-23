"""OAuth 2.1 / IndieAuth DTOs, VOs, and user-scoped token models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    RefreshToken,
)
from pydantic import model_validator

__all__ = [
    "LoginBridgeDecision",
    "LoginBridgeRequestDTO",
    "LoginBridgeResponseVO",
    "MCPScope",
    "OAuthErrorResponseVO",
    "SupernoteAccessToken",
    "SupernoteAuthorizationCode",
    "SupernoteRefreshToken",
]


class MCPScope(StrEnum):
    """OAuth 2.1 scopes supported by the Supernote server."""

    ALL = "supernote:all"
    """Full access to Supernote retrieval tools and REST APIs."""


class LoginBridgeDecision(StrEnum):
    """User consent decision submitted to POST /login-bridge."""

    APPROVE = "approve"
    DENY = "deny"


@dataclass
class LoginBridgeRequestDTO(DataClassJSONMixin):
    """Request DTO submitted by the Web UI to POST /login-bridge."""

    decision: LoginBridgeDecision = LoginBridgeDecision.APPROVE


@dataclass
class LoginBridgeResponseVO(DataClassJSONMixin):
    """Redirect response VO returned by POST /login-bridge."""

    redirect_url: str


@dataclass
class OAuthErrorResponseVO(DataClassJSONMixin):
    """RFC 6749 OAuth error response VO returned by /login-bridge."""

    error: str
    error_description: str | None = None

    class Config(BaseConfig):
        omit_none = True


class SupernoteAuthorizationCode(AuthorizationCode):
    """OAuth 2.1 authorization code associated with a Supernote user account."""

    user_id: int


class SupernoteAccessToken(AccessToken):
    """OAuth 2.1 access token associated with a Supernote user account."""

    user_id: int
    """Authenticated Supernote user ID."""

    actor: str = ""
    """Canonical domain event actor identifier (defaults to `oauth:<client_id>`)."""

    @model_validator(mode="after")
    def _ensure_canonical_actor(self) -> Self:
        if not self.actor.strip():
            client_id = (self.client_id or "").strip() or "unknown"
            self.actor = f"oauth:{client_id}"[:64]
        return self


class SupernoteRefreshToken(RefreshToken):
    """OAuth 2.1 refresh token associated with a Supernote user account."""

    user_id: int
