"""HTTP platform routes for the incremental per-user domain event feed.

Mounts `GET /api/extended/events` onto the main `aiohttp` application via
`async_setup_http` when the `events` component is enabled.

### Endpoint Contract

`GET /api/extended/events` (authenticated via `jwt_auth_middleware`):

- Query parameters parsed via `supernote.models.events.EventFeedRequestDTO`:
  - `syncToken` (optional): Opaque cursor returned by a previous call.
  - `eventTypes` (optional): Comma-separated list of exact event types or
    namespace wildcards (`vfs.*`, `note.*`, `schedule.*`, `summary.*`).
  - `fileId` (optional): Filter events to a specific VFS file ID.
  - `excludeActors` (optional): Comma-separated caller actor strings to omit
    from results. The special value ``self`` expands to the authenticated
    request's `REQUEST_ACTOR_KEY` for echo suppression.
  - `limit` (optional): Page size (`1..1000`, default `200`).
- Responses:
  - `200 OK`: `supernote.models.events.EventFeedListVO` JSON payload.
  - `400 Bad Request`: Malformed query parameters, invalid `syncToken`, or
    out-of-range `limit`.
  - `404 Not Found`: Authenticated user record not found.
  - `410 Gone`: `syncToken` predates retained event history (`CursorExpiredError`).
"""

from __future__ import annotations

import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue

from supernote.models.events import (
    DomainEventVO,
    EventFeedListVO,
    EventFeedRequestDTO,
)
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    REQUEST_ACTOR_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.user import UserService

from .service import EVENT_LOG_SERVICE_KEY, EventLogService

__all__ = [
    "async_setup_http",
    "routes",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/api/extended/events")
async def handle_list_events(request: web.Request) -> web.Response:
    """Serve the incremental per-user domain event feed (`GET /api/extended/events`)."""
    user_email = request[REQUEST_USER_KEY]
    try:
        req_dto = EventFeedRequestDTO.from_dict(dict(request.query))
    except (ValueError, TypeError, InvalidFieldValue) as err:
        return web.json_response({"error": f"Invalid Request: {err}"}, status=400)

    user_service: UserService = request.app[USER_SERVICE_KEY]
    event_log_service: EventLogService = request.app[EVENT_LOG_SERVICE_KEY]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    caller_actor = request[REQUEST_ACTOR_KEY]
    exclude_actors = (
        [
            caller_actor if actor.lower() == "self" else actor
            for actor in req_dto.exclude_actor_list
        ]
        if req_dto.exclude_actor_list
        else None
    )

    try:
        page = await event_log_service.list_events(
            user_id=user_id,
            sync_token=req_dto.sync_token,
            event_types=req_dto.event_type_list,
            file_id=req_dto.file_id,
            exclude_actors=exclude_actors,
            limit=req_dto.limit,
        )
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
        return web.json_response(vo.to_dict())
    except SupernoteError as err:
        return err.to_response()
    except Exception:
        logger.exception("Error listing domain events")
        return web.json_response({"error": "Internal server error"}, status=500)


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register the domain event feed HTTP routes on ``core.app``."""
    _ = registrar
    core.app.add_routes(routes)
