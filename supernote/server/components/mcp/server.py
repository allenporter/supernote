"""Streamable HTTP Model Context Protocol (MCP) Resource Server and tool handlers.

Defines `create_mcp_server`, `run_server`, `SupernoteTokenVerifier`, and the three MCP
tools exposed to authenticated AI agents:
- `list_notebooks`: Lists active `.note` files ordered by update timestamp.
- `search_notebook_chunks`: Performs vector similarity search via `supernote.server.components.search.service.SearchService`.
- `get_notebook_transcript`: Retrieves full or page-sliced OCR transcripts.

Validates both OAuth 2.1 Bearer tokens issued by `supernote.server.components.oauth.provider.SupernoteOAuthProvider`
and static Bearer API keys (`sn_...`) via `supernote.server.services.user.UserService`.
See `supernote.guides.mcp`.
"""

import logging
from typing import Any

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import (
    get_authenticated_user_id,
    instrument_mcp_tool,
)
from supernote.server.components.mcp.metrics import (
    MCPToolName,
    init_mcp_metrics,
)
from supernote.server.components.mcp.models import (
    ListNotebooksRequestDTO,
    ListNotebooksResponseVO,
    NotebookVO,
    SearchRequestDTO,
    SearchResponseVO,
    SearchResultVO,
    TranscriptRequestDTO,
    TranscriptResponseVO,
)
from supernote.server.components.oauth.models import (
    MCPScope,
    SupernoteAccessToken,
)
from supernote.server.components.search import SearchService
from supernote.server.components.transcript import TranscriptService
from supernote.server.services.user import (
    AuthMethod,
    UserService,
)

logger = logging.getLogger(__name__)
MAX_MCP_TOKEN_LENGTH = 4096

# Global services to be injected by the app
_services: dict[str, Any] = {
    "search_service": None,
    "transcript_service": None,
    "user_service": None,
}


def set_services(
    search_service: SearchService,
    user_service: UserService,
    transcript_service: TranscriptService | None = None,
) -> None:
    """Inject services into the MCP module."""
    _services["search_service"] = search_service
    _services["transcript_service"] = transcript_service
    _services["user_service"] = user_service


class SupernoteTokenVerifier(TokenVerifier):
    """Verifier that maps tokens to users using UserService."""

    def __init__(self, user_service: UserService):
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


async def _get_auth_user_id(ctx: Context) -> int | None:
    """Verify token and return user_id."""
    _ = ctx
    if not _services["user_service"]:
        raise ValueError("User service not initialized.")
    return get_authenticated_user_id()


@instrument_mcp_tool(MCPToolName.LIST_NOTEBOOKS)
async def list_notebooks(
    ctx: Context,
    limit: int = 20,
    name_filter: str | None = None,
) -> dict[str, Any]:
    """
    List active notebooks ordered by most recently updated.

    Args:
        limit: Maximum number of notebooks to return (default: 20).
        name_filter: Optional substring filter for notebook filenames.
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

    dto = ListNotebooksRequestDTO(limit=limit, name_filter=name_filter)
    notebooks = await search_service.list_notebooks(
        user_id=user_id,
        name_filter=dto.name_filter,
        limit=dto.limit,
    )
    vo_list = [
        NotebookVO(
            file_id=str(n.file_id),
            file_name=n.file_name,
            create_time=n.create_time,
            update_time=n.update_time,
        )
        for n in notebooks
    ]
    return ListNotebooksResponseVO(notebooks=vo_list).to_dict()


@instrument_mcp_tool(MCPToolName.SEARCH_NOTEBOOK_CHUNKS)
async def search_notebook_chunks(
    ctx: Context,
    query: str,
    top_n: int = 5,
    name_filter: str | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
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
            file_id=str(r.file_id),
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


@instrument_mcp_tool(MCPToolName.GET_NOTEBOOK_TRANSCRIPT)
async def get_notebook_transcript(
    ctx: Context,
    file_id: str,
    start_index: int | None = None,
    end_index: int | None = None,
) -> dict[str, Any]:
    """
    Retrieve the full transcript or a page range for a notebook.

    Args:
        file_id: The ID of the notebook.
        start_index: 0-based start page index (inclusive).
        end_index: 0-based end page index (inclusive).
    """
    transcript_service: TranscriptService | None = _services["transcript_service"]
    if not transcript_service:
        return create_error_response(
            "Services not initialized.", ErrorCode.INTERNAL_ERROR
        ).to_dict()

    user_id = await _get_auth_user_id(ctx)
    if user_id is None:
        return create_error_response(
            "Authentication failed. Please set a valid token in meta.",
            ErrorCode.UNAUTHORIZED,
        ).to_dict()

    dto = TranscriptRequestDTO(
        file_id=file_id,
        start_index=start_index,
        end_index=end_index,
    )
    try:
        parsed_file_id = int(dto.file_id)
    except ValueError:
        return create_error_response(
            f"Invalid file_id '{dto.file_id}': must be a numeric ID string.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()

    transcript = await transcript_service.get_transcript(
        user_id=user_id,
        file_id=parsed_file_id,
        start_index=dto.start_index,
        end_index=dto.end_index,
    )

    if transcript is None:
        return create_error_response(
            f"No transcript found for notebook {dto.file_id}.", ErrorCode.NOT_FOUND
        ).to_dict()

    return TranscriptResponseVO(transcript=transcript).to_dict()


def create_mcp_server(issuer_url: str, resource_server_url: str) -> MCPServer:
    """Create a new MCPServer instance and register tools."""
    init_mcp_metrics()
    token_verifier = SupernoteTokenVerifier(_services["user_service"])
    mcp = MCPServer(
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
    mcp.tool()(list_notebooks)
    mcp.tool()(search_notebook_chunks)
    mcp.tool()(get_notebook_transcript)
    return mcp


async def run_server(
    mcp: MCPServer, host: str, port: int, proxy_mode: str | None = None
) -> None:
    """Run the MCPServer with Streamable HTTP transport."""
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
