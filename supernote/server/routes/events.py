"""Routes for the incremental per-user domain event feed."""

import logging

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue

from supernote.models.events import (
    DomainEventVO,
    EventFeedListVO,
    EventFeedRequestDTO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    EVENT_LOG_SERVICE_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.event_log import EventLogService
from supernote.server.services.user import UserService

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/api/extended/events")
async def handle_list_events(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/events
    # Purpose: Incremental per-user domain event feed.
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

    try:
        page = await event_log_service.list_events(
            user_id=user_id,
            sync_token=req_dto.sync_token,
            event_types=req_dto.event_type_list,
            file_id=req_dto.file_id,
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
    except Exception as err:
        logger.exception("Error listing domain events")
        return web.json_response({"error": str(err)}, status=500)
