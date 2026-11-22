"""OAuth 2.1 and IndieAuth Authorization Server for the Supernote MCP server.

Implements `SupernoteOAuthProvider` and `create_auth_app` (mounted as an ASGI resource
on the main server port `8080` in `supernote.server.app.create_app`). Supports dynamic
IndieAuth-style URL client IDs, PKCE authorization code exchange (`/authorize`, `/token`),
token revocation (`/revoke`), and `/login-bridge` integration with the Web UI login flow.
Tokens are persisted with TTLs in `supernote.server.services.coordination.CoordinationService`,
tied to an `OAuthGrantDO` row the user can revoke, and verified by `supernote.server.mcp.server.SupernoteTokenVerifier`. See `supernote.guides.mcp`.
"""

import json
import secrets
import time
from typing import Any, override
from urllib.parse import quote

import yarl
from mashumaro.exceptions import InvalidFieldValue, MissingField
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import (
    InvalidRedirectUriError,
    InvalidScopeError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyHttpUrl, AnyUrl, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService
from supernote.server.utils.auth_utils import get_token_from_request

from .models import (
    LoginBridgeDecision,
    LoginBridgeRequestDTO,
    LoginBridgeResponseVO,
    MCPScope,
    OAuthErrorResponseVO,
    SupernoteAccessToken,
    SupernoteAuthorizationCode,
    SupernoteRefreshToken,
)


def _json_model_response(
    payload: DataClassJSONMixin, status_code: int = 200
) -> Response:
    """Serialize a Mashumaro DTO/VO as a non-cacheable JSON Starlette response."""
    return Response(
        content=payload.to_json(),
        status_code=status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


def _parse_oauth_url(raw: str) -> yarl.URL | None:
    """Parse an RFC 6749 / IndieAuth endpoint URL (canonical path, no userinfo or fragment)."""
    try:
        normalized = yarl.URL(raw)
        unnormalized = yarl.URL(raw, encoded=True)
    except ValueError:
        return None
    if (
        not normalized.scheme
        or not normalized.host
        or normalized.user is not None
        or normalized.password is not None
        or normalized.fragment
        or "\\" in unnormalized.path
        or unnormalized.path != normalized.path
    ):
        return None
    return normalized


class SupernoteOAuthClientInformationFull(OAuthClientInformationFull):
    """OAuth 2.1 Client Information for Supernote MCP."""

    @override
    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        """Allows redirect URI prefixes matching the registered origin and path boundary."""
        if redirect_uri is None:
            if self.redirect_uris and len(self.redirect_uris) == 1:
                return self.redirect_uris[0]
            raise InvalidRedirectUriError("Redirect URI must be specified")
        candidate = _parse_oauth_url(str(redirect_uri))
        if candidate is None:
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' is invalid")
        for registered_redirect_uri in self.redirect_uris or ():
            registered = _parse_oauth_url(str(registered_redirect_uri))
            if registered is None or candidate.origin() != registered.origin():
                continue
            reg_path = registered.path.rstrip("/")
            if (
                not reg_path
                or candidate.path == reg_path
                or candidate.path.startswith(f"{reg_path}/")
            ):
                return redirect_uri
        raise InvalidRedirectUriError(
            f"Redirect URI '{redirect_uri}' not in allowed list"
        )


class SupernoteOAuthProvider(
    OAuthAuthorizationServerProvider[
        SupernoteAuthorizationCode, SupernoteRefreshToken, SupernoteAccessToken
    ]
):
    """OAuth 2.1 Provider for Supernote MCP."""

    def __init__(
        self,
        user_service: UserService,
        coordination_service: CoordinationService,
        issuer_url: str,
    ):
        self.user_service = user_service
        self.issuer_url = issuer_url
        self._coordination = coordination_service

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve client information by IndieAuth HTTP(S) client URL."""
        parsed = _parse_oauth_url(client_id)
        if parsed is None or parsed.scheme not in ("http", "https"):
            return None
        try:
            validated_client_url = AnyHttpUrl(client_id)
        except ValidationError:
            return None
        return SupernoteOAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=[validated_client_url],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=MCPScope.ALL,
            token_endpoint_auth_method="none",
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Saves client information as part of registering it."""
        raise NotImplementedError("Dynamic client registration not supported")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Called as part of the /authorize endpoint."""
        resolved_scopes = params.scopes or (
            client.scope.split() if client.scope else [MCPScope.ALL]
        )
        return construct_redirect_uri(
            f"{self.issuer_url}/login-bridge",
            client_id=client.client_id,
            redirect_uri=(
                str(params.redirect_uri)
                if params.redirect_uri_provided_explicitly
                else None
            ),
            code_challenge=params.code_challenge,
            scope=" ".join(resolved_scopes),
            state=params.state,
            resource=params.resource,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> SupernoteAuthorizationCode | None:
        """Loads an AuthorizationCode by its code string."""
        key = f"mcp:auth_code:{authorization_code}"
        data = await self._coordination.get_value(key)
        if not data:
            return None
        return SupernoteAuthorizationCode.model_validate_json(data)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: SupernoteAuthorizationCode,
    ) -> OAuthToken:
        """Exchanges an authorization code for an access token and refresh token."""
        consumed = await self._coordination.pop_value(
            f"mcp:auth_code:{authorization_code.code}"
        )
        if not consumed:
            raise TokenError(
                error="invalid_grant",
                error_description="authorization code has already been used",
            )

        refresh_expires_at = int(time.time() + 86400 * 30)
        grant_id = await self.user_service.create_oauth_grant(
            authorization_code.user_id,
            authorization_code.client_id,
            authorization_code.scopes,
            expires_at=refresh_expires_at,
        )
        access_token = SupernoteAccessToken(
            token=secrets.token_urlsafe(32),
            user_id=authorization_code.user_id,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time() + 3600),
            grant_id=grant_id,
        )
        refresh_token = SupernoteRefreshToken(
            token=secrets.token_urlsafe(32),
            user_id=authorization_code.user_id,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            expires_at=refresh_expires_at,
            grant_id=grant_id,
        )

        # Store tokens
        await self._coordination.set_value(
            f"mcp:access_token:{access_token.token}",
            access_token.model_dump_json(),
            ttl=3600,
        )
        await self._coordination.set_value(
            f"mcp:refresh_token:{refresh_token.token}",
            refresh_token.model_dump_json(),
            ttl=86400 * 30,
        )

        return OAuthToken(
            access_token=access_token.token,
            refresh_token=refresh_token.token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    async def _parse_stored_token_data(self, data: str) -> dict[str, Any] | None:
        """Parse stored token JSON, migrating legacy email user_id values to integer IDs."""
        payload: dict[str, Any] = json.loads(data)
        raw_user_id = payload.get("user_id")
        # TODO(#442): Remove legacy email user_id migration once 30-day OAuth refresh tokens expire.
        if isinstance(raw_user_id, str) and not raw_user_id.isdigit():
            try:
                payload["user_id"] = await self.user_service.get_user_id(raw_user_id)
            except ValueError:
                return None
        return payload

    async def _grant_is_live(
        self, token: SupernoteAccessToken | SupernoteRefreshToken
    ) -> bool:
        """Whether the grant a stored token was issued under has not been revoked."""
        # TODO(#443): Reject tokens without a grant once 30-day pre-grant refresh tokens expire.
        if token.grant_id is None:
            return True
        return await self.user_service.verify_oauth_grant(token.user_id, token.grant_id)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> SupernoteRefreshToken | None:
        """Loads a RefreshToken by its token string."""
        key = f"mcp:refresh_token:{refresh_token}"
        data = await self._coordination.get_value(key)
        if not data:
            return None
        payload = await self._parse_stored_token_data(data)
        if payload is None:
            return None
        token = SupernoteRefreshToken.model_validate(payload)
        if not await self._grant_is_live(token):
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: SupernoteRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchanges a refresh token for an access token and refresh token."""
        new_access_token = SupernoteAccessToken(
            token=secrets.token_urlsafe(32),
            user_id=refresh_token.user_id,
            client_id=refresh_token.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=int(time.time() + 3600),
            grant_id=refresh_token.grant_id,
        )
        await self._coordination.set_value(
            f"mcp:access_token:{new_access_token.token}",
            new_access_token.model_dump_json(),
            ttl=3600,
        )
        return OAuthToken(
            access_token=new_access_token.token,
            refresh_token=refresh_token.token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(new_access_token.scopes),
        )

    async def load_access_token(self, token: str) -> SupernoteAccessToken | None:
        """Loads an access token by its token."""
        # 1. Try to load as an MCP access token from coordination service
        key = f"mcp:access_token:{token}"
        data = await self._coordination.get_value(key)
        if not data:
            return None
        payload = await self._parse_stored_token_data(data)
        if payload is None:
            return None
        access_token = SupernoteAccessToken.model_validate(payload)
        if not await self._grant_is_live(access_token):
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revokes an access or refresh token."""
        if isinstance(token, RefreshToken):
            await self._coordination.delete_value(f"mcp:refresh_token:{token.token}")
            if isinstance(token, SupernoteRefreshToken) and token.grant_id:
                await self.user_service.revoke_oauth_grant(
                    token.user_id, token.grant_id
                )
        else:
            await self._coordination.delete_value(f"mcp:access_token:{token.token}")


def create_auth_app(
    user_service: UserService,
    coordination_service: CoordinationService,
    issuer_url: str,
) -> Starlette:
    """Create a Starlette app for the MCP Authorization Server."""
    provider = SupernoteOAuthProvider(user_service, coordination_service, issuer_url)
    routes = create_auth_routes(
        provider=provider,
        issuer_url=AnyHttpUrl(issuer_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=False,
            valid_scopes=list(MCPScope),
            default_scopes=[MCPScope.ALL],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    app = Starlette(routes=routes, debug=True)

    # Add login-bridge route
    async def login_bridge(request: Request) -> Response:
        """Handle the OAuth 2.1 login & consent bridge between the Web UI and MCP server.

        Browser GET requests redirect to ``/#login?return_to=<bridge_url>`` so the Web UI
        authenticates the user (if needed) and renders an explicit OAuth Consent Card.
        Once the user approves or denies, the SPA issues an authenticated ``POST /login-bridge``
        request with ``x-access-token`` to validate the redirect target and mint a single-use
        authorization code (on approve) or return an ``access_denied`` redirect (on deny).
        """
        token = get_token_from_request(request)
        session = await user_service.verify_token(token) if token else None
        if session and session.is_api_key:
            return _json_model_response(
                OAuthErrorResponseVO(
                    error="forbidden",
                    error_description="API keys cannot authorize OAuth clients",
                ),
                status_code=403,
            )
        if request.method != "POST":
            return_target = (
                f"{request.url.path}?{request.url.query}"
                if request.url.query
                else request.url.path
            )
            login_url = f"/#login?return_to={quote(return_target, safe='')}"
            return RedirectResponse(
                url=login_url,
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )
        if not session:
            return _json_model_response(
                OAuthErrorResponseVO(error="unauthorized"),
                status_code=401,
            )

        raw_body = await request.body()
        if raw_body.strip():
            try:
                bridge_req = LoginBridgeRequestDTO.from_json(raw_body)
            except (MissingField, InvalidFieldValue, ValueError, TypeError):
                return _json_model_response(
                    OAuthErrorResponseVO(error="invalid_request"),
                    status_code=400,
                )
        else:
            bridge_req = LoginBridgeRequestDTO()

        # Extract OAuth params from query
        client_id = request.query_params.get("client_id")
        raw_redirect_uri = request.query_params.get("redirect_uri")
        code_challenge = request.query_params.get("code_challenge")
        state = request.query_params.get("state")
        raw_scope = request.query_params.get("scope")
        resource = request.query_params.get("resource")

        if not client_id or not code_challenge:
            return _json_model_response(
                OAuthErrorResponseVO(error="invalid_request"),
                status_code=400,
            )

        client_info = await provider.get_client(client_id)
        if not client_info:
            return _json_model_response(
                OAuthErrorResponseVO(
                    error="invalid_client",
                    error_description="Unrecognized or invalid client_id URL.",
                ),
                status_code=400,
            )

        try:
            parsed_redirect_arg = AnyUrl(raw_redirect_uri) if raw_redirect_uri else None
            validated_redirect_uri = client_info.validate_redirect_uri(
                parsed_redirect_arg
            )
        except (ValidationError, InvalidRedirectUriError):
            return _json_model_response(
                OAuthErrorResponseVO(
                    error="invalid_redirect_uri",
                    error_description=(
                        "Redirect URI does not match the requesting client origin and path."
                    ),
                ),
                status_code=400,
            )

        if bridge_req.decision == LoginBridgeDecision.DENY:
            denied_url = construct_redirect_uri(
                str(validated_redirect_uri),
                error="access_denied",
                state=state or None,
            )
            return _json_model_response(LoginBridgeResponseVO(redirect_url=denied_url))

        normalized_scope = (
            " ".join(raw_scope.split()) if raw_scope and raw_scope.strip() else None
        )
        try:
            validated_scopes = client_info.validate_scope(normalized_scope)
        except InvalidScopeError:
            return _json_model_response(
                OAuthErrorResponseVO(
                    error="invalid_scope",
                    error_description="Requested scope is not supported.",
                ),
                status_code=400,
            )
        scopes = validated_scopes or (
            client_info.scope.split() if client_info.scope else [MCPScope.ALL]
        )

        # Create the authorization code
        code_str = secrets.token_urlsafe(16)
        auth_code = SupernoteAuthorizationCode(
            code=code_str,
            user_id=session.user_id,
            client_id=client_id,
            redirect_uri=validated_redirect_uri,
            scopes=scopes,
            code_challenge=code_challenge,
            expires_at=int(time.time() + 600),
            redirect_uri_provided_explicitly=raw_redirect_uri is not None,
            resource=resource or None,
        )

        await coordination_service.set_value(
            f"mcp:auth_code:{code_str}",
            auth_code.model_dump_json(),
            ttl=600,
        )

        final_url = construct_redirect_uri(
            str(validated_redirect_uri),
            code=code_str,
            state=state or None,
        )
        return _json_model_response(LoginBridgeResponseVO(redirect_url=final_url))

    app.add_route("/login-bridge", login_bridge, methods=["GET", "POST"])
    return app
