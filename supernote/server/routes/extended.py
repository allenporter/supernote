"""Open Private Cloud extension routes (`/api/extended/*`) for API keys and OAuth grants.

Exposes non-device HTTP endpoints consumed by the Web UI and `supernote.client.extended.ExtendedClient`:
- `GET/POST/DELETE /api/extended/keys*`: Static Bearer API key management.
- `GET/DELETE /api/extended/oauth/grants*`: Revocable MCP OAuth client grant management.

See `supernote.guides.mcp`.
"""

import json
import logging
import time

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.base import BaseResponse
from supernote.models.extended import (
    ApiKeyListResponseVO,
    CreateApiKeyDTO,
    CreateApiKeyResponseVO,
    OAuthGrantListResponseVO,
)
from supernote.server.keys import (
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.user import UserService

from .decorators import interactive_session_only

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get("/api/extended/keys")
@interactive_session_only
async def handle_list_api_keys(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/keys
    # Purpose: List active static Bearer API keys for the authenticated user.
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    keys = await user_service.list_api_keys(user_id)
    return web.json_response(ApiKeyListResponseVO(keys=keys).to_dict())


@routes.post("/api/extended/keys")
@interactive_session_only
async def handle_create_api_key(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/keys
    # Purpose: Generate and return a new static Bearer API key.
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = CreateApiKeyDTO.from_dict(await request.json())
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    expires_at: int | None = None
    if req_dto.expires_in_days is not None:
        if req_dto.expires_in_days <= 0 or req_dto.expires_in_days > 3650:
            return web.json_response(
                {"error": "expiresInDays must be between 1 and 3650"}, status=400
            )
        expires_at = int(time.time()) + req_dto.expires_in_days * 86400

    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    try:
        raw_token, vo = await user_service.create_api_key(
            user_id, req_dto.name, expires_at=expires_at
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)

    return web.json_response(
        CreateApiKeyResponseVO(
            id=vo.id,
            name=vo.name,
            key=raw_token,
            created_at=vo.created_at,
            expires_at=vo.expires_at,
        ).to_dict()
    )


@routes.delete("/api/extended/keys/{key_id}")
@interactive_session_only
async def handle_delete_api_key(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/extended/keys/{key_id}
    # Purpose: Revoke an existing static Bearer API key.
    user_email = request[REQUEST_USER_KEY]
    key_id = request.match_info["key_id"]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)

    revoked = await user_service.revoke_api_key(user_id, key_id)
    if not revoked:
        return web.json_response(
            {"error": "API key not found or already revoked"}, status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())


@routes.get("/api/extended/oauth/grants")
@interactive_session_only
async def handle_list_oauth_grants(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/oauth/grants
    # Purpose: List MCP OAuth clients the authenticated user has authorized.
    user_email = request[REQUEST_USER_KEY]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)
    grants = await user_service.list_oauth_grants(user_id)
    return web.json_response(OAuthGrantListResponseVO(grants=grants).to_dict())


@routes.delete("/api/extended/oauth/grants/{grant_id}")
@interactive_session_only
async def handle_revoke_oauth_grant(request: web.Request) -> web.Response:
    # Endpoint: DELETE /api/extended/oauth/grants/{grant_id}
    # Purpose: Disconnect an MCP OAuth client, ending its access and refresh tokens.
    user_email = request[REQUEST_USER_KEY]
    grant_id = request.match_info["grant_id"]
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(user_email)

    revoked = await user_service.revoke_oauth_grant(user_id, grant_id)
    if not revoked:
        return web.json_response(
            {"error": "OAuth grant not found or already revoked"}, status=404
        )

    return web.json_response(BaseResponse(success=True).to_dict())
