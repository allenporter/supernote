"""Tests for the EventsClient API wrapper."""

from typing import Any

from aiohttp import web

from supernote.client.auth import ConstantAuth
from supernote.client.client import Client
from supernote.client.events import EventsClient


async def test_events_client_list_events(aiohttp_client: Any) -> None:
    """Verify EventsClient serializes query parameters and parses EventFeedListVO."""
    recorded: list[tuple[str, str, dict[str, str]]] = []

    async def handle_csrf(_request: web.Request) -> web.Response:
        return web.Response(headers={"X-XSRF-TOKEN": "csrf-token"})

    async def handle_events(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, dict(request.query)))
        return web.json_response(
            {
                "success": True,
                "events": [
                    {
                        "seq": "105",
                        "timestamp": 1700000000000,
                        "eventType": "vfs.created",
                        "actor": "user:web",
                        "entityType": "file",
                        "entityId": "10",
                        "relatedFileId": "10",
                        "payload": {"path": "/NOTE/a.note"},
                    }
                ],
                "nextSyncToken": "djE6MTA1",
                "hasMore": False,
            }
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handle_csrf)
    app.router.add_get("/api/extended/events", handle_events)

    test_client = await aiohttp_client(app)
    base_client = Client(
        test_client.session,
        host=str(test_client.make_url("")),
        auth=ConstantAuth("token-123"),
    )
    events_client = EventsClient(base_client)

    events_vo = await events_client.list_events(
        sync_token="djE6MTAw",
        event_types=["vfs.*", "note.*"],
        file_id=10,
        limit=50,
    )
    assert len(events_vo.events) == 1
    assert events_vo.events[0].seq == "105"
    assert events_vo.events[0].event_type == "vfs.created"
    assert events_vo.events[0].related_file_id == 10
    assert events_vo.next_sync_token == "djE6MTA1"
    assert events_vo.has_more is False

    assert recorded == [
        (
            "GET",
            "/api/extended/events",
            {
                "syncToken": "djE6MTAw",
                "limit": "50",
                "eventTypes": "vfs.*,note.*",
                "fileId": "10",
            },
        ),
    ]
