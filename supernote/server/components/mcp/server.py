"""Streamable HTTP Model Context Protocol (MCP) Resource Server and tool handlers.

Defines `create_mcp_server`, `run_server`, `SupernoteTokenVerifier`, and the MCP
tools exposed to authenticated AI agents:
- `list_notebooks`: Lists active `.note` files ordered by update timestamp.
- `search_notebook_chunks`: Performs vector similarity search via `supernote.server.services.search.SearchService`.
- `get_notebook_transcript`: Retrieves full or page-sliced OCR transcripts.
- `list_tasks`, `create_task`, `update_task`, `delete_task`: Schedule task CRUD with notebook deep-links.
- `list_events`: Incremental per-user domain event feed polling with cursor and actor filtering.

Validates both OAuth 2.1 Bearer tokens issued by `supernote.server.components.mcp.auth.SupernoteOAuthProvider`
and static Bearer API keys (`sn_...`) via `supernote.server.services.user.UserService`.
See `supernote.guides.mcp`.
"""

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, cast

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from supernote.models.base import ErrorCode, create_error_response
from supernote.models.events import DomainEventVO, EventFeedListVO
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.components.mcp.models import (
    DeleteTaskResponseVO,
    ListNotebooksRequestDTO,
    ListNotebooksResponseVO,
    ListTasksResponseVO,
    MCPScope,
    NotebookVO,
    SearchRequestDTO,
    SearchResponseVO,
    SearchResultVO,
    SupernoteAccessToken,
    TaskGroupVO,
    TaskResponseVO,
    TaskVO,
    TranscriptRequestDTO,
    TranscriptResponseVO,
)
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.events import bind_event_actor
from supernote.server.exceptions import (
    CursorExpiredError,
    SupernoteError,
    TaskGroupNotFound,
)
from supernote.server.metrics import (
    MCPToolName,
    init_mcp_metrics,
    track_mcp_tool_call,
)
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.event_log import EventLogService
from supernote.server.services.schedule import ScheduleService
from supernote.server.services.search import SearchService
from supernote.server.services.user import (
    API_KEY_PREFIX,
    OAUTH_ACCESS_TOKEN_KEY_PREFIX,
    UserService,
)

logger = logging.getLogger(__name__)
MAX_MCP_TOKEN_LENGTH = 4096
_VALID_TASK_STATUSES = frozenset({"needsAction", "completed"})

_P = ParamSpec("_P")

# Global services to be injected by the app
_services: dict[str, Any] = {
    "search_service": None,
    "user_service": None,
    "coordination_service": None,
    "schedule_service": None,
    "event_log_service": None,
}


def set_services(
    search_service: SearchService,
    user_service: UserService,
    coordination_service: CoordinationService,
    *,
    schedule_service: ScheduleService | None = None,
    event_log_service: EventLogService | None = None,
) -> None:
    """Inject services into the MCP module."""
    _services["search_service"] = search_service
    _services["user_service"] = user_service
    _services["coordination_service"] = coordination_service
    _services["schedule_service"] = schedule_service
    _services["event_log_service"] = event_log_service


class SupernoteTokenVerifier(TokenVerifier):
    """Verifier that maps tokens to users using UserService."""

    def __init__(
        self, user_service: UserService, coordination_service: CoordinationService
    ):
        self.user_service = user_service
        self.coordination_service = coordination_service

    async def verify_token(self, token: str) -> SupernoteAccessToken | None:
        if not token or len(token) > MAX_MCP_TOKEN_LENGTH:
            return None

        if not token.startswith(API_KEY_PREFIX):
            key = f"{OAUTH_ACCESS_TOKEN_KEY_PREFIX}{token}"
            data = await self.coordination_service.get_value(key)
            if data:
                token_data = await self.user_service.parse_oauth_token_payload(data)
                if token_data is None:
                    return None
                client_id = str(token_data.get("client_id") or "").strip() or "unknown"
                return SupernoteAccessToken(
                    token=token,
                    user_id=token_data["user_id"],
                    client_id=client_id,
                    scopes=token_data.get("scopes", []),
                    resource=token_data.get("resource"),
                    actor=f"oauth:{client_id}"[:64],
                )

        session = await self.user_service.verify_token(token)
        if not session:
            return None
        return SupernoteAccessToken(
            token=token,
            user_id=session.user_id,
            client_id="api_key" if session.is_api_key else "session",
            scopes=[MCPScope.ALL],
            expires_at=session.expires_at,
            actor=session.actor,
        )


def _get_auth_token(ctx: Context) -> SupernoteAccessToken | None:
    """Return the authenticated MCP access token for the current request context."""
    if not _services["user_service"]:
        raise ValueError("User service not initialized.")

    if not (auth_context := auth_context_var.get()):
        return None
    return cast(SupernoteAccessToken, auth_context.access_token)


async def _get_auth_user_id(ctx: Context) -> int | None:
    """Verify token and return user_id."""
    token = _get_auth_token(ctx)
    return token.user_id if token is not None else None


class _MCPToolError(Exception):
    """Internal control-flow exception carrying a structured MCP error response dict."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response


def _instrument_mcp_tool(
    tool: MCPToolName,
) -> Callable[
    [Callable[_P, Awaitable[dict[str, Any]]]],
    Callable[_P, Awaitable[dict[str, Any]]],
]:
    """Wrap an MCP tool handler to record Prometheus call and latency metrics."""

    def decorator(
        fn: Callable[_P, Awaitable[dict[str, Any]]],
    ) -> Callable[_P, Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> dict[str, Any]:
            with track_mcp_tool_call(tool=tool) as call:
                try:
                    result = await fn(*args, **kwargs)
                except _MCPToolError as err:
                    result = err.response
                call.set_succeeded(result.get("success") is True)
                return result

        return wrapper

    return decorator


@_instrument_mcp_tool(MCPToolName.LIST_NOTEBOOKS)
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


@_instrument_mcp_tool(MCPToolName.SEARCH_NOTEBOOK_CHUNKS)
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


@_instrument_mcp_tool(MCPToolName.GET_NOTEBOOK_TRANSCRIPT)
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

    transcript = await search_service.get_transcript(
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


def _require_mcp_context[T](
    ctx: Context, service_key: str, _service_type: type[T]
) -> tuple[T, SupernoteAccessToken]:
    """Return `(service, auth_token)` or raise `_MCPToolError` when uninitialized/unauthenticated."""
    service = _services[service_key]
    if not service:
        raise _MCPToolError(
            create_error_response(
                "Services not initialized.", ErrorCode.INTERNAL_ERROR
            ).to_dict()
        )
    token = _get_auth_token(ctx)
    if token is None:
        raise _MCPToolError(
            create_error_response(
                "Authentication failed. Please set a valid token in meta.",
                ErrorCode.UNAUTHORIZED,
            ).to_dict()
        )
    return cast(T, service), token


def _decode_task_link(links: str | None) -> ScheduleTaskLinkDTO | None:
    """Decode a Base64 `ScheduleTaskLinkDTO` string when valid."""
    if not links:
        return None
    try:
        return ScheduleTaskLinkDTO.from_b64(links)
    except (ValueError, TypeError, LookupError):
        return None


def _task_do_to_vo(task: ScheduleTaskDO) -> TaskVO:
    """Convert a `ScheduleTaskDO` row into an MCP `TaskVO` with decoded link metadata."""
    return TaskVO(
        task_id=task.task_id,
        task_list_id=task.task_list_id,
        title=task.title,
        detail=task.detail,
        status=task.status,
        importance=task.importance,
        due_time=task.due_time,
        completed_time=task.completed_time,
        create_time=task.create_time,
        update_time=task.update_time,
        link=_decode_task_link(task.links),
    )


def _encode_task_link(
    *,
    linked_file_id: str | None,
    linked_file_path: str | None,
    linked_page_id: str | None,
    linked_page_number: int | None,
    existing: ScheduleTaskLinkDTO | None = None,
) -> str:
    """Encode notebook/page deep-link parameters into a Base64 `ScheduleTaskLinkDTO`."""
    dto = ScheduleTaskLinkDTO(
        app_name=existing.app_name if existing is not None else "Note",
        path=(
            linked_file_path
            if linked_file_path is not None
            else (existing.path if existing is not None else "")
        ),
        page=(
            linked_page_number
            if linked_page_number is not None
            else (existing.page if existing is not None else 1)
        ),
        file_id=(
            linked_file_id
            if linked_file_id is not None
            else (existing.file_id if existing is not None else None)
        ),
        page_id=(
            linked_page_id
            if linked_page_id is not None
            else (existing.page_id if existing is not None else None)
        ),
        task_title=existing.task_title if existing is not None else None,
    )
    return dto.to_b64()


@_instrument_mcp_tool(MCPToolName.LIST_TASKS)
async def list_tasks(
    ctx: Context,
    group_id: str | None = None,
    include_completed: bool = False,
    file_id: str | None = None,
) -> dict[str, Any]:
    """List Supernote To-Do task groups and tasks, including decoded notebook deep-links."""
    schedule_service, token = _require_mcp_context(
        ctx, "schedule_service", ScheduleService
    )

    groups = await schedule_service.list_groups(token.user_id)
    tasks = await schedule_service.list_tasks(token.user_id, group_id=group_id)

    target_file_id = file_id.strip() if file_id else None
    task_vos: list[TaskVO] = []
    for task in tasks:
        if not include_completed and task.status == "completed":
            continue
        vo = _task_do_to_vo(task)
        if target_file_id is not None and (
            vo.link is None or (vo.link.file_id or "").strip() != target_file_id
        ):
            continue
        task_vos.append(vo)

    group_vos = [
        TaskGroupVO(
            task_list_id=g.task_list_id,
            title=g.title,
            create_time=g.create_time,
            update_time=g.update_time,
        )
        for g in groups
    ]
    return ListTasksResponseVO(groups=group_vos, tasks=task_vos).to_dict()


@_instrument_mcp_tool(MCPToolName.CREATE_TASK)
async def create_task(
    ctx: Context,
    title: str,
    detail: str = "",
    status: str = "needsAction",
    importance: str | None = None,
    due_time: int | None = None,
    group_id: str | None = None,
    linked_file_id: str | None = None,
    linked_file_path: str | None = None,
    linked_page_id: str | None = None,
    linked_page_number: int | None = None,
) -> dict[str, Any]:
    """Create a Supernote To-Do task, optionally deep-linked to a notebook page."""
    schedule_service, token = _require_mcp_context(
        ctx, "schedule_service", ScheduleService
    )

    if status not in _VALID_TASK_STATUSES:
        return create_error_response(
            f"Invalid status '{status}': expected 'needsAction' or 'completed'.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()
    if linked_page_number is not None and linked_page_number < 1:
        return create_error_response(
            "linked_page_number must be >= 1.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()
    if due_time is not None and due_time < 0:
        return create_error_response(
            "due_time must be >= 0.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()

    has_link = any(
        v is not None
        for v in (
            linked_file_id,
            linked_file_path,
            linked_page_id,
            linked_page_number,
        )
    )
    links = (
        _encode_task_link(
            linked_file_id=linked_file_id,
            linked_file_path=linked_file_path,
            linked_page_id=linked_page_id,
            linked_page_number=linked_page_number,
        )
        if has_link
        else None
    )
    completed_time_ms = int(time.time() * 1000) if status == "completed" else None

    try:
        with bind_event_actor(token.actor):
            task = await schedule_service.create_task(
                user_id=token.user_id,
                group_id=group_id,
                title=title,
                detail=detail,
                status=status,
                importance=importance,
                due_time=None if due_time == 0 else due_time,
                completed_time_ms=completed_time_ms,
                links=links,
            )
    except TaskGroupNotFound as err:
        return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
    except ValueError as err:
        return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()

    return TaskResponseVO(task=_task_do_to_vo(task)).to_dict()


@_instrument_mcp_tool(MCPToolName.UPDATE_TASK)
async def update_task(
    ctx: Context,
    task_id: str,
    title: str | None = None,
    detail: str | None = None,
    status: str | None = None,
    importance: str | None = None,
    due_time: int | None = None,
    group_id: str | None = None,
    linked_file_id: str | None = None,
    linked_file_path: str | None = None,
    linked_page_id: str | None = None,
    linked_page_number: int | None = None,
    clear_link: bool = False,
) -> dict[str, Any]:
    """Partially update an existing Supernote To-Do task and/or its notebook deep-link."""
    schedule_service, token = _require_mcp_context(
        ctx, "schedule_service", ScheduleService
    )

    if status is not None and status not in _VALID_TASK_STATUSES:
        return create_error_response(
            f"Invalid status '{status}': expected 'needsAction' or 'completed'.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()
    if linked_page_number is not None and linked_page_number < 1:
        return create_error_response(
            "linked_page_number must be >= 1.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()
    if due_time is not None and due_time < 0:
        return create_error_response(
            "due_time must be >= 0.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()

    has_link_fields = any(
        v is not None
        for v in (
            linked_file_id,
            linked_file_path,
            linked_page_id,
            linked_page_number,
        )
    )
    if clear_link and has_link_fields:
        return create_error_response(
            "clear_link cannot be combined with linked_* parameters.",
            ErrorCode.BAD_REQUEST,
        ).to_dict()

    existing_task = await schedule_service.get_task(token.user_id, task_id)
    if existing_task is None:
        return create_error_response(
            f"Task {task_id} not found.", ErrorCode.NOT_FOUND
        ).to_dict()

    updates: dict[str, Any] = {}
    if title is not None:
        updates["title"] = title
    if detail is not None:
        updates["detail"] = detail
    if status is not None:
        updates["status"] = status
        updates["completed_time"] = (
            (existing_task.completed_time or int(time.time() * 1000))
            if status == "completed"
            else None
        )
    if importance is not None:
        updates["importance"] = importance
    if due_time is not None:
        updates["due_time"] = None if due_time == 0 else due_time
    if group_id is not None:
        updates["task_list_id"] = group_id

    if clear_link:
        updates["links"] = None
    elif has_link_fields:
        updates["links"] = _encode_task_link(
            linked_file_id=linked_file_id,
            linked_file_path=linked_file_path,
            linked_page_id=linked_page_id,
            linked_page_number=linked_page_number,
            existing=_decode_task_link(existing_task.links),
        )

    if not updates:
        return create_error_response(
            "No update fields provided.", ErrorCode.BAD_REQUEST
        ).to_dict()

    try:
        with bind_event_actor(token.actor):
            updated = await schedule_service.update_task(
                token.user_id, task_id, **updates
            )
    except TaskGroupNotFound as err:
        return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
    except ValueError as err:
        return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()

    if updated is None:
        return create_error_response(
            f"Task {task_id} not found.", ErrorCode.NOT_FOUND
        ).to_dict()
    return TaskResponseVO(task=_task_do_to_vo(updated)).to_dict()


@_instrument_mcp_tool(MCPToolName.DELETE_TASK)
async def delete_task(ctx: Context, task_id: str) -> dict[str, Any]:
    """Delete a Supernote To-Do task by ID."""
    schedule_service, token = _require_mcp_context(
        ctx, "schedule_service", ScheduleService
    )

    with bind_event_actor(token.actor):
        deleted = await schedule_service.delete_task(token.user_id, task_id)
    if not deleted:
        return create_error_response(
            f"Task {task_id} not found.", ErrorCode.NOT_FOUND
        ).to_dict()
    return DeleteTaskResponseVO(deleted=True).to_dict()


@_instrument_mcp_tool(MCPToolName.LIST_EVENTS)
async def list_events(
    ctx: Context,
    sync_token: str | None = None,
    event_types: list[str] | None = None,
    file_id: str | None = None,
    exclude_actors: list[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Poll the incremental per-user domain event feed using a `sync_token` cursor."""
    event_log_service, token = _require_mcp_context(
        ctx, "event_log_service", EventLogService
    )

    parsed_file_id: int | None = None
    if file_id is not None:
        try:
            parsed_file_id = int(file_id)
        except ValueError:
            return create_error_response(
                f"Invalid file_id '{file_id}': must be a numeric ID string.",
                ErrorCode.BAD_REQUEST,
            ).to_dict()

    resolved_exclude = (
        [
            token.actor if actor.strip().lower() == "self" else actor.strip()
            for actor in exclude_actors
            if actor.strip()
        ]
        if exclude_actors
        else None
    )

    try:
        page = await event_log_service.list_events(
            user_id=token.user_id,
            sync_token=sync_token,
            event_types=event_types,
            file_id=parsed_file_id,
            exclude_actors=resolved_exclude,
            limit=limit,
        )
    except CursorExpiredError as err:
        return create_error_response(err.message, ErrorCode.GONE).to_dict()
    except SupernoteError as err:
        return create_error_response(err.message, ErrorCode.BAD_REQUEST).to_dict()

    return EventFeedListVO(
        events=[
            DomainEventVO(
                seq=str(ev.seq),
                timestamp=ev.timestamp_ms,
                event_type=ev.event_type,
                actor=ev.actor,
                entity_type=ev.entity_type,
                entity_id=ev.entity_id,
                related_file_id=ev.related_file_id,
                payload=ev.payload,
            )
            for ev in page.events
        ],
        next_sync_token=page.next_sync_token,
        has_more=page.has_more,
    ).to_dict()


def create_mcp_server(issuer_url: str, resource_server_url: str) -> MCPServer:
    """Create a new MCPServer instance and register tools."""
    init_mcp_metrics()
    token_verifier = SupernoteTokenVerifier(
        _services["user_service"], _services["coordination_service"]
    )
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
    mcp.tool()(list_tasks)
    mcp.tool()(create_task)
    mcp.tool()(update_task)
    mcp.tool()(delete_task)
    mcp.tool()(list_events)
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
