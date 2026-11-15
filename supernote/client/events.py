"""Client for Supernote Domain Events APIs."""

from supernote.models.events import (
    DomainEntityType,
    DomainEventType,
    DomainEventVO,
    EventFeedListVO,
    EventFeedRequestDTO,
)

from .client import Client

__all__ = [
    "DomainEntityType",
    "DomainEventType",
    "DomainEventVO",
    "EventFeedListVO",
    "EventFeedRequestDTO",
    "EventsClient",
]


class EventsClient:
    """Client for polling the incremental per-user domain event feed."""

    def __init__(self, client: Client) -> None:
        """Initialize the EventsClient."""
        self._client = client

    async def list_events(
        self,
        *,
        sync_token: str | None = None,
        event_types: list[str] | None = None,
        file_id: int | None = None,
        limit: int = 200,
    ) -> EventFeedListVO:
        """Poll a user's incremental domain event feed (`GET /api/extended/events`).

        Args:
            sync_token: Opaque `next_sync_token` from a previous response, or
                `None` to read from the beginning of retained event history.
            event_types: Optional list of event type filters. Accepts exact
                `DomainEventType` values (defined in `supernote.models.events`,
                e.g. `DomainEventType.NOTE_PAGE_TRANSCRIBED`) or namespace prefix
                globs (`'vfs.*'`, `'note.*'`, `'schedule.*'`, `'summary.*'`).
            file_id: Optional VFS file ID to scope events to a single file/notebook.
            limit: Maximum number of events per page (`1..1000`, default `200`).

        Returns:
            `EventFeedListVO` with `events`, `next_sync_token` (persist and pass
            on the next call), and `has_more` (`True` when another page is
            immediately available).
        """
        dto = EventFeedRequestDTO(
            sync_token=sync_token,
            event_types=",".join(event_types) if event_types else None,
            file_id=file_id,
            limit=limit,
        )
        params = {k: str(v) for k, v in dto.to_dict().items()}
        return await self._client.get_json(
            "/api/extended/events", EventFeedListVO, params=params
        )
