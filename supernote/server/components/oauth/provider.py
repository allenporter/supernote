"""OAuth 2.1 provider for the Supernote server.

Implements `SupernoteOAuthProvider`, which identifies clients by Client ID Metadata
Documents (see `.client_metadata`) and exchanges PKCE authorization codes. Short-lived
authorization codes live in `supernote.server.services.coordination.CoordinationService`;
access and refresh tokens belong to a grant row managed by
`supernote.server.services.user.UserService`.
"""

import logging
import time
from typing import override

import yarl
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyHttpUrl, AnyUrl, ValidationError

from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import OAUTH_ACCESS_TOKEN_TTL_SECONDS, UserService

from .client_metadata import (
    LOOPBACK_HOSTS,
    ClientMetadataError,
    ClientMetadataUnavailableError,
    DocumentFetcher,
    fetch_client_metadata_document,
    resolve_client_metadata,
)
from .models import (
    MCPScope,
    SupernoteAccessToken,
    SupernoteAuthorizationCode,
    SupernoteRefreshToken,
)

logger = logging.getLogger(__name__)

UNAVAILABLE_RETRY_SECONDS = 10
UNAVAILABLE_MEMO_SIZE = 1024


def _without_loopback_port(uri: str) -> str:
    """Drop the port of an http loopback redirect URI (RFC 8252, RFC 9700 4.1.3)."""
    url = yarl.URL(uri, encoded=True)
    if url.scheme == "http" and url.raw_host in LOOPBACK_HOSTS:
        return str(url.with_port(None))
    return uri


def _parse_oauth_url(raw: str) -> yarl.URL | None:
    """Parse an RFC 6749 / IndieAuth endpoint URL (canonical path, no userinfo or fragment)."""
    try:
        normalized = yarl.URL(raw)
        unnormalized = yarl.URL(raw, encoded=True)
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
    except ValueError:
        return None
    return normalized


class SupernoteOAuthClientInformationFull(OAuthClientInformationFull):
    """OAuth 2.1 Client Information for a client with a metadata document."""

    @override
    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        """Require an exact match with a registered URI; loopback ports may vary."""
        if redirect_uri is None:
            if self.redirect_uris and len(self.redirect_uris) == 1:
                return self.redirect_uris[0]
            raise InvalidRedirectUriError("Redirect URI must be specified")
        candidate = str(redirect_uri)
        for registered in self.redirect_uris or ():
            if candidate == str(registered) or _without_loopback_port(
                candidate
            ) == _without_loopback_port(str(registered)):
                return redirect_uri
        raise InvalidRedirectUriError(
            f"Redirect URI '{redirect_uri}' not in allowed list"
        )


class IndieAuthClientInformation(SupernoteOAuthClientInformationFull):
    """A client identified by a URL that serves no metadata document."""

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


def _indieauth_client(client_id: str) -> IndieAuthClientInformation | None:
    """An IndieAuth-style client whose redirects share the client ID's origin and path."""
    parsed = _parse_oauth_url(client_id)
    if parsed is None or parsed.scheme not in ("http", "https"):
        return None
    try:
        validated_client_url = AnyHttpUrl(client_id)
    except ValidationError:
        return None
    return IndieAuthClientInformation(
        client_id=client_id,
        redirect_uris=[validated_client_url],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=MCPScope.ALL,
        token_endpoint_auth_method="none",
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
        fetch_document: DocumentFetcher | None = None,
    ):
        self.user_service = user_service
        self.issuer_url = issuer_url
        self._coordination = coordination_service
        self._fetch_document = fetch_document or fetch_client_metadata_document
        self._unavailable_until: dict[str, float] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve a client from its Client ID Metadata Document.

        A client ID that serves no document falls back to IndieAuth-style matching.
        Raises `ClientMetadataUnavailableError` when the document cannot be fetched
        right now, so a network failure is never reported as an invalid client. The
        failure is remembered briefly, because the SDK's `/authorize` error path asks
        for the client a second time.
        """
        now = time.monotonic()
        if self._unavailable_until.get(client_id, 0.0) > now:
            raise ClientMetadataUnavailableError("client metadata is unavailable")
        try:
            metadata = await resolve_client_metadata(
                self._coordination, self._fetch_document, client_id, self.issuer_url
            )
        except ClientMetadataUnavailableError as err:
            logger.warning("OAuth client %s is unavailable: %s", client_id, err)
            if len(self._unavailable_until) >= UNAVAILABLE_MEMO_SIZE:
                self._unavailable_until.clear()
            self._unavailable_until[client_id] = now + UNAVAILABLE_RETRY_SECONDS
            raise
        except ClientMetadataError as err:
            logger.info("Rejected OAuth client %s: %s", client_id, err)
            return None
        if metadata is None:
            return _indieauth_client(client_id)
        return SupernoteOAuthClientInformationFull(
            client_id=client_id,
            client_name=metadata.client_name,
            redirect_uris=[AnyUrl(uri) for uri in metadata.redirect_uris],
            grant_types=metadata.grant_types,
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

        access_token, refresh_token = await self.user_service.create_oauth_grant(
            authorization_code.user_id,
            authorization_code.client_id,
            authorization_code.scopes,
        )
        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=OAUTH_ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> SupernoteRefreshToken | None:
        """Loads a RefreshToken by its token string."""
        grant = await self.user_service.load_oauth_refresh_token(refresh_token)
        if grant is None:
            return None
        return SupernoteRefreshToken(
            token=refresh_token,
            user_id=grant.user_id,
            client_id=grant.client_id,
            scopes=grant.scopes,
            expires_at=grant.expires_at,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: SupernoteRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchanges a refresh token for a new access token on the same grant."""
        access_token = await self.user_service.refresh_oauth_grant(refresh_token.token)
        if access_token is None:
            raise TokenError(
                error="invalid_grant",
                error_description="refresh token has been revoked",
            )
        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token.token,
            token_type="Bearer",
            expires_in=OAUTH_ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(refresh_token.scopes),
        )

    async def load_access_token(self, token: str) -> SupernoteAccessToken | None:
        """Loads an access token by its token."""
        grant = await self.user_service.load_oauth_access_token(token)
        if grant is None:
            return None
        return SupernoteAccessToken(
            token=token,
            user_id=grant.user_id,
            client_id=grant.client_id,
            scopes=grant.scopes,
            expires_at=grant.expires_at,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revokes an access or refresh token (a refresh token ends its grant)."""
        await self.user_service.revoke_oauth_token(token.token)
