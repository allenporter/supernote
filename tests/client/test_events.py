"""Unit tests for `supernote.client.events.EventsClient`."""

from unittest.mock import AsyncMock

from supernote.client.client import Client
from supernote.client.events import EventsClient
from supernote.models.events import EventFeedListVO


async def test_events_client_list_events_serializes_query_params() -> None:
    """Verify EventsClient serializes syncToken, eventTypes, fileId, excludeActors, and limit."""
    mock_client = AsyncMock(spec=Client)
    expected_vo = EventFeedListVO(events=[], next_sync_token="djE6NQ", has_more=False)
    mock_client.get_json.return_value = expected_vo

    events_client = EventsClient(mock_client)
    result = await events_client.list_events(
        sync_token="djE6MQ",
        event_types=["note.*", "schedule.task_updated"],
        file_id=42,
        exclude_actors=["self", "system:processor"],
        limit=50,
    )

    assert result == expected_vo
    mock_client.get_json.assert_awaited_once_with(
        "/api/extended/events",
        EventFeedListVO,
        params={
            "syncToken": "djE6MQ",
            "eventTypes": "note.*,schedule.task_updated",
            "fileId": "42",
            "excludeActors": "self,system:processor",
            "limit": "50",
        },
    )
