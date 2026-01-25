import json
import logging
from typing import Any, Optional

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.mcp.models import (
    SearchRequestDTO,
    SearchResponseVO,
    SearchResultVO,
    SupernoteAccessToken,
    TranscriptResponseVO,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.search import SearchService
from supernote.server.services.user import UserService

logger = logging.getLogger(__name__)

# Global services to be injected by the app
_services: dict[str, Any] = {
    "search_service": None,
    "user_service": None,
    "coordination_service": None,
}


def set_services(
    search_service: SearchService,
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Inject services into the MCP module."""
    _services["search_service"] = search_service
    _services["user_service"] = user_service
    _services["coordination_service"] = coordination_service


class SupernoteTokenVerifier(TokenVerifier):
    """Verifier that maps tokens to users using UserService."""

    def __init__(
        self, user_service: UserService, coordination_service: CoordinationService
    ):
        self.user_service = user_service
        self.coordination_service = coordination_service

    async def verify_token(self, token: str) -> SupernoteAccessToken | None:
        key = f"mcp:access_token:{token}"
        data = await self.coordination_service.get_value(key)
        if not data:
            return None
        token_data = json.loads(data)
        return SupernoteAccessToken(
            token=token,
            user_id=token_data.get("user_id"),
            client_id=token_data.get("client_id", "unknown"),
            scopes=token_data.get("scopes", []),
            resource=token_data.get("resource"),
        )


async def _get_auth_user_id(ctx: Context) -> Optional[int]:
    """Verify token and return user_id."""
    if not (user_service_raw := _services["user_service"]):
        raise ValueError("User service not initialized.")
    user_service: UserService = user_service_raw

    # Try to get user from MCP Auth Context (e.g. Bearer token)
    if not (auth_context := auth_context_var.get()):
        return None
    token: SupernoteAccessToken = auth_context.access_token  # type: ignore[assignment]
    if not token.user_id:
        return None
    return await user_service.get_user_id(token.user_id)


async def search_notebook_chunks(
    ctx: Context,
    query: str,
    top_n: int = 5,
    name_filter: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
) -> dict[str, Any]:
    """
    Search for notebook content chunks based on semantic similarity.

    Args:
        query: The semantic search query.
        top_n: Number of results to return (default: 5).
        name_filter: Optional substring filter for notebook filenames.
        date_after: Filter for notes created after this date (ISO 8601).
        date_before: Filter for notes created before this date (ISO 8601).
    """
    search_service: SearchService = _services["search_service"]
    if not search_service:
        return create_error_response(
            "Services not initialized.", ErrorCode.INTERNAL_ERROR
        ).to_dict()

    user_id = await _get_auth_user_id(ctx)
    if user_id is None:
        return create_error_response(
            "Authentication failed. Please set a valid token in meta.",
            ErrorCode.UNAUTHORIZED,
        ).to_dict()

    # Use the DTO to validate internally
    dto = SearchRequestDTO(
        query=query,
        top_n=top_n,
        name_filter=name_filter,
        date_after=date_after,
        date_before=date_before,
    )

    results = await search_service.search_chunks(
        user_id=user_id,
        query=dto.query,
        top_n=dto.top_n,
        name_filter=dto.name_filter,
        date_after=dto.date_after,
        date_before=dto.date_before,
    )

    if not results:
        return SearchResponseVO(results=[]).to_dict()

    vo_list = [
        SearchResultVO(
            file_id=r.file_id,
            file_name=r.file_name,
            page_index=r.page_index,
            page_id=r.page_id,
            score=r.score,
            text_preview=r.text_preview,
            date=r.date,
        )
        for r in results
    ]

    return SearchResponseVO(results=vo_list).to_dict()


async def get_notebook_transcript(
    ctx: Context,
    file_id: int,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
) -> dict[str, Any]:
    """
    Retrieve the full transcript or a page range for a notebook.

    Args:
        file_id: The ID of the notebook.
        start_index: 0-based start page index (inclusive).
        end_index: 0-based end page index (inclusive).
    """
    search_service: SearchService = _services["search_service"]
    if not search_service:
        return create_error_response(
            "Services not initialized.", ErrorCode.INTERNAL_ERROR
        ).to_dict()

    user_id = await _get_auth_user_id(ctx)
    if user_id is None:
        return create_error_response(
            "Authentication failed. Please set a valid token in meta.",
            ErrorCode.UNAUTHORIZED,
        ).to_dict()

    transcript = await search_service.get_transcript(
        user_id=user_id,
        file_id=file_id,
        start_index=start_index,
        end_index=end_index,
    )

    if transcript is None:
        return create_error_response(
            f"No transcript found for notebook {file_id}.", ErrorCode.NOT_FOUND
        ).to_dict()

    return TranscriptResponseVO(transcript=transcript).to_dict()


def create_mcp_server(issuer_url: str, resource_server_url: str) -> FastMCP:
    """Create a new FastMCP server instance and register tools."""
    token_verifier = SupernoteTokenVerifier(
        _services["user_service"], _services["coordination_service"]
    )
    mcp = FastMCP(
        "Supernote Retrieval",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_server_url),
        ),
        token_verifier=token_verifier,
    )
    mcp.tool()(search_notebook_chunks)
    mcp.tool()(get_notebook_transcript)
    return mcp


async def run_server(
    mcp: FastMCP, host: str, port: int, proxy_mode: Optional[str] = None
) -> None:
    """Run the FastMCP server with Streamable HTTP transport."""
    mcp.settings.host = host
    mcp.settings.port = port

    # Relax security for custom host headers (e.g. k8s ingress) only if proxy mode is enabled.
    # This prevents DNS rebinding attacks while allowing operation behind proxies.
    if proxy_mode == "relaxed":
        logger.info(
            f"Proxy mode {proxy_mode} detected. Relaxing MCP transport security."
        )
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    logger.info(f"Starting MCP server on {host}:{port} using streamable-http...")
    await mcp.run_streamable_http_async()
