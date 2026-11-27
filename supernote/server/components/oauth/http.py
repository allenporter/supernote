"""HTTP platform setup and Starlette ASGI app for the OAuth 2.1 Authorization Server.

The OAuth 2.1 Authorization Server runs on the primary `aiohttp` server (`8080`),
separate from the MCP Resource Server (`8081`, which only serves `/mcp` and
`/.well-known/oauth-protected-resource/mcp`). Because `mcp.server.auth.routes.create_auth_routes`
returns Starlette routes, this module wraps them (plus `/login-bridge`) in an in-process
`Starlette` app and bridges it into `aiohttp` via `aiohttp_asgi.ASGIResource`.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import cast
from urllib.parse import quote

import yarl
from aiohttp_asgi import ASGIResource
from mashumaro.exceptions import InvalidFieldValue, MissingField
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.auth.routes import build_metadata, cors_middleware, create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import (
    InvalidRedirectUriError,
    InvalidScopeError,
    OAuthClientInformationFull,
)
from pydantic import AnyHttpUrl, AnyUrl, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import SessionState, UserService
from supernote.server.utils.auth_utils import get_token_from_request

from .client_metadata import ClientMetadataUnavailableError
from .models import (
    LoginBridgeClientVO,
    LoginBridgeDecision,
    LoginBridgeRequestDTO,
    LoginBridgeResponseVO,
    MCPScope,
    OAuthErrorResponseVO,
    SupernoteAuthorizationCode,
)
from .provider import SupernoteOAuthProvider

__all__ = ["async_setup_http", "create_auth_app"]

logger = logging.getLogger(__name__)


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


class _BridgeError(Exception):
    """An OAuth error response from the login bridge."""

    def __init__(self, error: OAuthErrorResponseVO, status_code: int) -> None:
        super().__init__(error.error)
        self.error = error
        self.status_code = status_code


async def _bridge_error(request: Request, exc: Exception) -> Response:
    """Render a `_BridgeError` as its OAuth JSON error response."""
    error = cast(_BridgeError, exc)
    return _json_model_response(error.error, status_code=error.status_code)


async def _client_metadata_unavailable(request: Request, exc: Exception) -> Response:
    """Section 6.1: a transient document failure is a 503, never a redirect."""
    return _json_model_response(
        OAuthErrorResponseVO(
            error="temporarily_unavailable",
            error_description="The client's metadata document could not be fetched.",
        ),
        status_code=503,
    )


def create_auth_app(
    user_service: UserService,
    coordination_service: CoordinationService,
    issuer_url: str,
) -> Starlette:
    """Create the Starlette ASGI app for the OAuth 2.1 Authorization Server."""
    provider = SupernoteOAuthProvider(user_service, coordination_service, issuer_url)
    metadata_issuer = AnyHttpUrl(issuer_url)
    # RFC 9207: authorization responses carry the metadata issuer, verbatim.
    issuer = str(metadata_issuer)
    registration_options = ClientRegistrationOptions(
        enabled=False,
        valid_scopes=list(MCPScope),
        default_scopes=[MCPScope.ALL],
    )
    revocation_options = RevocationOptions(enabled=True)
    routes = create_auth_routes(
        provider=provider,
        issuer_url=metadata_issuer,
        client_registration_options=registration_options,
        revocation_options=revocation_options,
    )
    # Clients are public and identified by metadata documents, not shared secrets.
    metadata = build_metadata(
        metadata_issuer, None, registration_options, revocation_options
    ).model_copy(
        update={
            "client_id_metadata_document_supported": True,
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
        }
    )
    routes = [
        Route(
            route.path,
            endpoint=cors_middleware(
                MetadataHandler(metadata).handle, ["GET", "OPTIONS"]
            ),
            methods=["GET", "OPTIONS"],
        )
        if route.path == "/.well-known/oauth-authorization-server"
        else route
        for route in routes
    ]
    app = Starlette(
        routes=routes,
        debug=True,
        exception_handlers={
            ClientMetadataUnavailableError: _client_metadata_unavailable,
            _BridgeError: _bridge_error,
        },
    )

    async def verify_session(request: Request) -> SessionState | None:
        """The caller's interactive session, or None; API keys and OAuth tokens get a 403."""
        token = get_token_from_request(request)
        session = await user_service.verify_token(token) if token else None
        if session and not session.is_interactive_session:
            raise _BridgeError(
                OAuthErrorResponseVO(
                    error="forbidden",
                    error_description=(
                        "API keys cannot authorize OAuth clients"
                        if session.is_api_key
                        else "OAuth tokens cannot authorize OAuth clients"
                    ),
                ),
                status_code=403,
            )
        return session

    def require(session: SessionState | None) -> SessionState:
        """The session, or a 401 when the caller is not signed in."""
        if not session:
            raise _BridgeError(OAuthErrorResponseVO(error="unauthorized"), 401)
        return session

    async def resolve_client(
        request: Request, client_id: str
    ) -> tuple[OAuthClientInformationFull, AnyUrl]:
        """The requesting client and the redirect URI a decision will be sent to."""
        client_info = await provider.get_client(client_id)
        if not client_info:
            raise _BridgeError(
                OAuthErrorResponseVO(
                    error="invalid_client",
                    error_description="The client's metadata document is missing or invalid.",
                ),
                status_code=400,
            )
        raw_redirect_uri = request.query_params.get("redirect_uri")
        try:
            parsed_redirect_arg = AnyUrl(raw_redirect_uri) if raw_redirect_uri else None
            return client_info, client_info.validate_redirect_uri(parsed_redirect_arg)
        except (ValidationError, InvalidRedirectUriError) as err:
            raise _BridgeError(
                OAuthErrorResponseVO(
                    error="invalid_redirect_uri",
                    error_description=(
                        "Redirect URI is not registered for this client."
                    ),
                ),
                status_code=400,
            ) from err

    async def login_bridge_client(request: Request) -> Response:
        """Describe the requesting client for the Web UI consent card."""
        require(await verify_session(request))
        client_id = request.query_params.get("client_id")
        if not client_id:
            raise _BridgeError(OAuthErrorResponseVO(error="invalid_request"), 400)
        client_info, redirect_uri = await resolve_client(request, client_id)
        client_host = yarl.URL(client_id).raw_host or client_id
        return _json_model_response(
            LoginBridgeClientVO(
                client_name=client_info.client_name or client_host,
                client_host=client_host,
                redirect_uri=str(redirect_uri),
            )
        )

    async def login_bridge(request: Request) -> Response:
        """Handle the OAuth 2.1 login & consent bridge between the Web UI and OAuth clients."""
        session = await verify_session(request)
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
        session = require(session)

        raw_body = await request.body()
        if raw_body.strip():
            try:
                bridge_req = LoginBridgeRequestDTO.from_json(raw_body)
            except (MissingField, InvalidFieldValue, ValueError, TypeError) as err:
                raise _BridgeError(
                    OAuthErrorResponseVO(error="invalid_request"), 400
                ) from err
        else:
            bridge_req = LoginBridgeRequestDTO()

        client_id = request.query_params.get("client_id")
        raw_redirect_uri = request.query_params.get("redirect_uri")
        code_challenge = request.query_params.get("code_challenge")
        state = request.query_params.get("state")
        raw_scope = request.query_params.get("scope")
        resource = request.query_params.get("resource")

        if not client_id or not code_challenge:
            raise _BridgeError(OAuthErrorResponseVO(error="invalid_request"), 400)

        client_info, validated_redirect_uri = await resolve_client(request, client_id)
        if bridge_req.redirect_uri is not None and bridge_req.redirect_uri != str(
            validated_redirect_uri
        ):
            raise _BridgeError(
                OAuthErrorResponseVO(
                    error="invalid_redirect_uri",
                    error_description=(
                        "The client's redirect URI changed. Reload to review it."
                    ),
                ),
                status_code=400,
            )

        if bridge_req.decision == LoginBridgeDecision.DENY:
            denied_url = construct_redirect_uri(
                str(validated_redirect_uri),
                error="access_denied",
                state=state or None,
                iss=issuer,
            )
            return _json_model_response(LoginBridgeResponseVO(redirect_url=denied_url))

        normalized_scope = (
            " ".join(raw_scope.split()) if raw_scope and raw_scope.strip() else None
        )
        try:
            validated_scopes = client_info.validate_scope(normalized_scope)
        except InvalidScopeError as err:
            raise _BridgeError(
                OAuthErrorResponseVO(
                    error="invalid_scope",
                    error_description="Requested scope is not supported.",
                ),
                status_code=400,
            ) from err
        scopes = validated_scopes or (
            client_info.scope.split() if client_info.scope else [MCPScope.ALL]
        )

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
            iss=issuer,
        )
        return _json_model_response(LoginBridgeResponseVO(redirect_url=final_url))

    app.add_route("/login-bridge", login_bridge, methods=["GET", "POST"])
    app.add_route("/login-bridge/client", login_bridge_client, methods=["GET"])
    return app


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register the OAuth 2.1 ASGI resource and bounded metrics paths."""
    logger.info("Mounting OAuth 2.1 Authorization Server at %s", core.config.base_url)
    auth_app = create_auth_app(
        core.user_service,
        core.coordination,
        core.config.base_url,
    )
    asgi_resource = ASGIResource(auth_app)
    known_paths = (
        path
        for route in auth_app.routes
        if isinstance(path := getattr(route, "path", None), str)
    )
    registrar.add_public_resource(asgi_resource, known_paths=known_paths)
