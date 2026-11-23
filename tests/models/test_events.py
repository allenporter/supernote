"""Tests for domain event feed data models."""

from supernote.models.events import (
    DomainEntityType,
    DomainEventType,
    DomainEventVO,
    EventFeedListVO,
    EventFeedRequestDTO,
)


def test_event_feed_request_dto() -> None:
    assert DomainEventType.NOTE_PAGE_TRANSCRIBED == "note.page_transcribed"
    assert DomainEntityType.NOTE_PAGE == "note_page"

    req = EventFeedRequestDTO(
        sync_token="djE6MTAw",
        event_types="vfs.*, note.*",
        file_id=772252421643567298,
        exclude_actors="self, api_key:abc",
        limit=50,
    )
    assert req.event_type_list == ["vfs.*", "note.*"]
    assert req.exclude_actor_list == ["self", "api_key:abc"]
    assert req.to_dict() == {
        "syncToken": "djE6MTAw",
        "eventTypes": "vfs.*, note.*",
        "fileId": "772252421643567298",
        "excludeActors": "self, api_key:abc",
        "limit": 50,
    }
    assert EventFeedRequestDTO.from_dict(req.to_dict()) == req
    assert EventFeedRequestDTO().event_type_list is None
    assert EventFeedRequestDTO().exclude_actor_list is None


def test_event_feed_list_vo() -> None:
    ev = DomainEventVO(
        seq="772252421643567001",
        timestamp=1_700_000_000_000,
        event_type="note.page_transcribed",
        actor="system:processor",
        entity_type="note_page",
        entity_id="772252421643567298:0",
        related_file_id=772252421643567298,
        payload={"page_index": 0, "current_text": "hello"},
    )
    feed = EventFeedListVO(
        events=[ev],
        next_sync_token="772252421643567001",
        has_more=True,
    )
    data = feed.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "events": [
            {
                "seq": "772252421643567001",
                "timestamp": 1_700_000_000_000,
                "eventType": "note.page_transcribed",
                "actor": "system:processor",
                "entityType": "note_page",
                "entityId": "772252421643567298:0",
                "relatedFileId": "772252421643567298",
                "payload": {"page_index": 0, "current_text": "hello"},
            }
        ],
        "nextSyncToken": "772252421643567001",
        "hasMore": True,
    }
    assert EventFeedListVO.from_dict(data) == feed
