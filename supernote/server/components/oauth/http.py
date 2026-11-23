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
from urllib.parse import quote

from aiohttp_asgi import ASGIResource
from mashumaro.exceptions import InvalidFieldValue, MissingField
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import InvalidRedirectUriError, InvalidScopeError
from pydantic import AnyHttpUrl, AnyUrl, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService
from supernote.server.utils.auth_utils import get_token_from_request

from .models import (
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


def create_auth_app(
    user_service: UserService,
    coordination_service: CoordinationService,
    issuer_url: str,
) -> Starlette:
    """Create the Starlette ASGI app for the OAuth 2.1 Authorization Server."""
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

    async def login_bridge(request: Request) -> Response:
        """Handle the OAuth 2.1 login & consent bridge between the Web UI and OAuth clients."""
        token = get_token_from_request(request)
        session = await user_service.verify_token(token) if token else None
        if session and not session.is_interactive_session:
            error_description = (
                "API keys cannot authorize OAuth clients"
                if session.is_api_key
                else "OAuth tokens cannot authorize OAuth clients"
            )
            return _json_model_response(
                OAuthErrorResponseVO(
                    error="forbidden",
                    error_description=error_description,
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
