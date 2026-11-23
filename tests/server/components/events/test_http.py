"""Tests for GET /api/extended/events domain event feed route."""

from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.events import EventsClient
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from supernote.client.schedule import ScheduleClient
from supernote.server.components.events import EVENT_LOG_SERVICE_KEY
from supernote.server.services.user import UserService


@pytest.fixture
async def authenticated_client(
    client: TestClient,
    auth_headers: dict[str, str],
) -> Client:
    """Fixture for an authenticated Supernote HTTP Client."""
    token = auth_headers["x-access-token"]

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    return Client(client.session, auth=TokenAuth(), host=str(client.make_url("")))


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


async def test_list_events_invalid_query_params(
    events_client: EventsClient,
    authenticated_client: Client,
) -> None:
    """Verify invalid limit, syncToken, or query field types raise BadRequestException."""
    with pytest.raises(BadRequestException):
        await events_client.list_events(limit=0)

    with pytest.raises(BadRequestException):
        await events_client.list_events(sync_token="bad")

    with pytest.raises(BadRequestException):
        await authenticated_client.get("/api/extended/events", params={"fileId": "abc"})


async def test_list_events_error_responses(
    client: TestClient,
    events_client: EventsClient,
    user_service: UserService,
) -> None:
    """Verify user-not-found (404) and unexpected service failure (500) responses."""
    assert client.app is not None
    event_log_service = client.app[EVENT_LOG_SERVICE_KEY]

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(NotFoundException),
    ):
        await events_client.list_events()

    with (
        patch.object(
            event_log_service, "list_events", side_effect=RuntimeError("boom")
        ),
        pytest.raises(ApiException),
    ):
        await events_client.list_events()


async def test_list_events_api_key_actor_and_exclude_self(
    client: TestClient,
    authenticated_client: Client,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify API key mutations record api_key:<id> actor and excludeActors=self suppresses self-echo."""
    raw_key, created_key = await user_service.create_api_key(
        test_user_id, "Magic Todo Agent"
    )

    class _ApiKeyAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return raw_key

    api_key_http_client = Client(
        client.session, auth=_ApiKeyAuth(), host=str(client.make_url("/"))
    )
    web_schedule = ScheduleClient(authenticated_client)
    agent_schedule = ScheduleClient(api_key_http_client)
    agent_events = EventsClient(api_key_http_client)

    web_task = await web_schedule.create_task(group_id=None, title="Human task")
    agent_task = await agent_schedule.create_task(group_id=None, title="Agent task")

    # Without exclude_actors, both tasks appear with distinct actors.
    full_feed = await agent_events.list_events(event_types=["schedule.*"])
    assert [(e.entity_id, e.actor) for e in full_feed.events] == [
        (web_task.task_id, "user:web"),
        (agent_task.task_id, f"api_key:{created_key.id}"),
    ]

    # With exclude_actors=["SELF"], case-insensitive self expansion skips the agent's own echo.
    filtered = await agent_events.list_events(
        event_types=["schedule.*"], exclude_actors=["SELF"]
    )
    assert [(e.entity_id, e.actor) for e in filtered.events] == [
        (web_task.task_id, "user:web"),
    ]

    # Next poll advances past the excluded self-authored event.
    after = await agent_events.list_events(
        sync_token=filtered.next_sync_token,
        event_types=["schedule.*"],
        exclude_actors=["self"],
    )
    assert after.events == []
    assert after.next_sync_token == full_feed.next_sync_token
