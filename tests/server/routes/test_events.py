"""Tests for GET /api/extended/events domain event feed route."""

from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.events import EventsClient
from supernote.server.keys import EVENT_LOG_SERVICE_KEY
from supernote.server.services.user import UserService


@pytest.fixture
def events_client(authenticated_client: Client) -> EventsClient:
    """Fixture for EventsClient."""
    return EventsClient(authenticated_client)


async def test_list_events_pagination_and_filtering(
    client: TestClient,
    events_client: EventsClient,
    test_user_id: int,
) -> None:
    """Verify GET /api/extended/events sync_token pagination and event filtering."""
    assert client.app is not None
    event_log_service = client.app[EVENT_LOG_SERVICE_KEY]

    ev1 = await event_log_service.append(
        user_id=test_user_id,
        event_type="vfs.created",
        entity_type="file",
        entity_id="772252421643567298",
        related_file_id=772252421643567298,
        actor="device:SN001",
        payload={"path": "/NOTE/todo.note"},
        timestamp_ms=1_700_000_001_000,
    )
    ev2 = await event_log_service.append(
        user_id=test_user_id,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="772252421643567298:0",
        related_file_id=772252421643567298,
        actor="system:processor",
        payload={"page_index": 0, "current_text": "buy milk"},
        timestamp_ms=1_700_000_002_000,
    )

    feed = await events_client.list_events(limit=1)
    assert [e.seq for e in feed.events] == [str(ev1.seq)]
    assert feed.events[0].related_file_id == 772252421643567298
    assert feed.next_sync_token is not None
    assert feed.next_sync_token != str(ev1.seq)
    assert feed.has_more is True

    feed2 = await events_client.list_events(sync_token=feed.next_sync_token)
    assert [e.seq for e in feed2.events] == [str(ev2.seq)]
    assert feed2.has_more is False

    filtered = await events_client.list_events(
        event_types=["note.*"],
        file_id=772252421643567298,
    )
    assert [e.seq for e in filtered.events] == [str(ev2.seq)]


@pytest.mark.parametrize(
    "bad_query",
    ["fileId=abc", "limit=abc", "limit=0", "syncToken=bad"],
)
async def test_list_events_invalid_query_params(
    client: TestClient,
    auth_headers: dict[str, str],
    bad_query: str,
) -> None:
    """Verify invalid fileId, limit, or syncToken query parameters return HTTP 400."""
    resp = await client.get(f"/api/extended/events?{bad_query}", headers=auth_headers)
    assert resp.status == 400


async def test_list_events_error_responses(
    client: TestClient,
    auth_headers: dict[str, str],
    user_service: UserService,
) -> None:
    """Verify user-not-found (404) and unexpected service failure (500) responses."""
    assert client.app is not None
    event_log_service = client.app[EVENT_LOG_SERVICE_KEY]

    with patch.object(user_service, "get_user_id", return_value=None):
        not_found = await client.get("/api/extended/events", headers=auth_headers)
        assert not_found.status == 404

    with patch.object(
        event_log_service, "list_events", side_effect=RuntimeError("boom")
    ):
        err_resp = await client.get("/api/extended/events", headers=auth_headers)
        assert err_resp.status == 500
