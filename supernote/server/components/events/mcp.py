"""MCP platform setup exposing the incremental `list_events` domain event feed tool.

Registers `list_events` onto `McpRegistrar` via `async_setup_mcp`, backed by
`EventLogService`. Supports cursor pagination (`sync_token`), exact or wildcard
`event_types` filtering, `file_id` scoping, case-insensitive `exclude_actors`
``"self"`` echo suppression, and `ErrorCode.GONE` (`"410"`) cursor expiration
signaling.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.models.events import DomainEventVO, EventFeedListVO
from supernote.server.components.mcp import (
    McpRegistrar,
    get_authenticated_actor,
    get_authenticated_user_id,
)
from supernote.server.core import ServerCore
from supernote.server.exceptions import CursorExpiredError, InvalidInputError

from .models import DEFAULT_FEED_LIMIT
from .service import EVENT_LOG_SERVICE_KEY

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register `list_events` onto `registrar`."""
    event_log_service = core.app[EVENT_LOG_SERVICE_KEY]

    async def list_events(
        ctx: Context,
        sync_token: str | None = None,
        event_types: list[str] | None = None,
        file_id: str | None = None,
        exclude_actors: list[str] | None = None,
        limit: int = DEFAULT_FEED_LIMIT,
    ) -> dict[str, Any]:
        """Poll the authenticated user's incremental domain event log.

        Args:
            sync_token: Opaque `nextSyncToken` from a previous call to resume
                incrementally, or omitted to read from retained history.
            event_types: Optional list of exact event types or namespace
                wildcards (e.g., ``["note.*", "schedule.*"]``).
            file_id: Optional numeric VFS file ID string to filter events by
                `relatedFileId`.
            exclude_actors: Optional list of caller actor strings to omit from
                results. The special value ``"self"`` (case-insensitive)
                expands to the authenticated MCP caller's canonical actor for
                echo suppression.
            limit: Maximum number of events to return (`1..1000`, default `200`).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None or (
            caller_actor := get_authenticated_actor()
        ) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()

        parsed_file_id: int | None = None
        if file_id is not None:
            try:
                parsed_file_id = int(file_id)
            except ValueError:
                return create_error_response(
                    f"Invalid file_id '{file_id}': must be a numeric ID string.",
                    ErrorCode.BAD_REQUEST,
                ).to_dict()

        resolved_exclude_actors = (
            [
                caller_actor if actor.lower() == "self" else actor
                for actor in exclude_actors
            ]
            if exclude_actors
            else None
        )

        try:
            page = await event_log_service.list_events(
                user_id=user_id,
                sync_token=sync_token,
                event_types=event_types,
                file_id=parsed_file_id,
                exclude_actors=resolved_exclude_actors,
                limit=limit,
            )
        except InvalidInputError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except CursorExpiredError as err:
            return create_error_response(str(err), ErrorCode.GONE).to_dict()

        vo = EventFeedListVO(
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
        )
        return vo.to_dict()

    registrar.add_tool(list_events)
