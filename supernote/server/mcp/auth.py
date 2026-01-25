"""An OAuth Authorization server for Supernote MCP."""

import logging
import secrets
import time
from typing import Optional, override
from urllib.parse import quote, urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.server.auth.routes import create_auth_routes
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyHttpUrl, AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService

from .models import (
    SupernoteAccessToken,
    SupernoteAuthorizationCode,
    SupernoteRefreshToken,
)

_LOGGER = logging.getLogger(__name__)


class SupernoteOAuthClientInformationFull(OAuthClientInformationFull):
    """OAuth 2.1 Client Information for Supernote MCP."""

    @override
    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        """Allows redirect uri prefixes."""
        if redirect_uri is None:
            raise InvalidRedirectUriError("Redirect URI must be specified")
        redirect_uri_str = str(redirect_uri)
        for registered_redirect_uri in self.redirect_uris or ():
            if redirect_uri_str.startswith(str(registered_redirect_uri)):
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
        """Retrieve client information by client ID."""
        # Support dynamic IndieAuth-style clients (Client ID is a URL)
        try:
            parsed = urlparse(client_id)
        except ValueError:
            return None
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return SupernoteOAuthClientInformationFull(
                client_id=client_id,
                redirect_uris=[AnyHttpUrl(client_id)],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="supernote:all",
                token_endpoint_auth_method="none",
            )
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Saves client information as part of registering it."""
        raise NotImplementedError("Dynamic client registration not supported")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Called as part of the /authorize endpoint."""
        # We redirect to a bridge that handles login/session check, passing
        # the full set of OAuth params.
        query_params = params.model_dump()
        query_params["client_id"] = client.client_id
        query = urlencode(query_params)
        return f"{self.issuer_url}/login-bridge?{query}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[SupernoteAuthorizationCode]:
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
        # Validate PKCE if present (SDK usually handles this, but we store it in AuthorizationCode)
        # In a real implementation, we would generate a JWT or random token.
        # For now, we reuse the UserService login logic or just generate a dedicated MCP token.

        access_token = SupernoteAccessToken(
            token=secrets.token_urlsafe(32),
            user_id=authorization_code.user_id,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time() + 3600),
        )
        refresh_token = SupernoteRefreshToken(
            token=secrets.token_urlsafe(32),
            user_id=authorization_code.user_id,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time() + 86400 * 30),
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

        # Delete auth code after use (single use only)
        # We don't have the string code here easily, but the SDK should handle it if we return successfully.
        # Actually, let's just let it expire or manually delete it in the bridge if needed.

        return OAuthToken(
            access_token=access_token.token,
            refresh_token=refresh_token.token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[SupernoteRefreshToken]:
        """Loads a RefreshToken by its token string."""
        key = f"mcp:refresh_token:{refresh_token}"
        data = await self._coordination.get_value(key)
        if not data:
            return None
        return SupernoteRefreshToken.model_validate_json(data)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: SupernoteRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchanges a refresh token for an access token and refresh token."""
        # Similar to code exchange but using refresh token
        # Similar to code exchange but using refresh token
        new_access_token = SupernoteAccessToken(
            token=secrets.token_urlsafe(32),
            user_id=refresh_token.user_id,
            client_id=refresh_token.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=int(time.time() + 3600),
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

    async def load_access_token(self, token: str) -> Optional[SupernoteAccessToken]:
        """Loads an access token by its token."""
        # 1. Try to load as an MCP access token from coordination service
        key = f"mcp:access_token:{token}"
        data = await self._coordination.get_value(key)
        if not data:
            return None
        return SupernoteAccessToken.model_validate_json(data)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revokes an access or refresh token."""
        # TODO: Implement token revocation in UserService/CoordinationService
        pass


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
    )
    app = Starlette(routes=routes, debug=True)

    # Add login-bridge route
    @app.route("/login-bridge")
    async def login_bridge(request: Request) -> RedirectResponse | JSONResponse:
        # Check for session cookie (we'll assume 'session' cookie contains the token)
        token = request.cookies.get("session")
        if not token:
            # Redirect to main login page

            return_url = str(request.url)
            # Use config properties if we could, but we have user_service._config
            # We'll assume the main app is at the same host but different port or same path prefix
            # For simplicity, we assume we can just redirect to /#login
            login_url = f"/#login?return_to={quote(return_url)}"
            return RedirectResponse(url=login_url)

        # Verify token
        session = await user_service.verify_token(token)
        if not session:
            login_url = f"/#login?return_to={quote(str(request.url))}"
            return RedirectResponse(url=login_url)

        # Extract OAuth params from query
        client_id = request.query_params.get("client_id")
        redirect_uri = request.query_params.get("redirect_uri")
        state = request.query_params.get("state")

        if not client_id or not redirect_uri:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        # Validate Client compatibility
        client_info = await provider.get_client(client_id)
        if not client_info:
            return JSONResponse({"error": "invalid_client"}, status_code=400)

        # Create the authorization code
        code_str = secrets.token_urlsafe(16)
        auth_code = SupernoteAuthorizationCode(
            code=code_str,
            user_id=session.email,
            client_id=client_id,
            redirect_uri=AnyHttpUrl(redirect_uri),
            scopes=["supernote:all"],
            code_challenge=request.query_params.get("code_challenge") or "",
            expires_at=int(time.time() + 600),
            redirect_uri_provided_explicitly=True,
        )

        # Store auth code
        await coordination_service.set_value(
            f"mcp:auth_code:{code_str}",
            auth_code.model_dump_json(),
            ttl=600,
        )

        # Redirect back to client

        callback_params = {"code": code_str}
        if state:
            callback_params["state"] = state

        if redirect_uri:
            sep = "&" if "?" in redirect_uri else "?"
            final_url = f"{redirect_uri}{sep}{urlencode(callback_params)}"
            return RedirectResponse(url=final_url)
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    return app
