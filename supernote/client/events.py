"""Client for the Supernote incremental domain event feed.

The domain event feed (`GET /api/extended/events`) exposes an append-only,
strictly ordered per-user log of state transitions across VFS files and
folders (`vfs.*`), notebook page structures and OCR transcripts (`note.*`),
schedule tasks (`schedule.*`), and AI summaries (`summary.*`). The same
unified event log and `sync_token` checkpointing also back MCP (Model Context
Protocol) event tools and resource update notifications so MCP clients and
external agents can consume workspace changes through a single consistent
contract.

Instead of polling and diffing full folder trees, notebook transcripts, or
task lists on a timer, consumers (such as MCP clients, background agents, sync
workers, or UI clients) can:
1. Call `EventsClient.list_events()` with `sync_token=None` on initial
   bootstrap (or resume from a persisted `next_sync_token`).
2. Page forward while `has_more` is `True`, persisting `next_sync_token` after
   each processed batch.
3. Listen for lightweight Socket.IO `event_log_cursor` notifications (or poll
   periodically) and pass the saved `sync_token` to fetch only new mutations.
4. If the server returns `HTTP 410 Gone` (`CursorExpiredError`) because a
   long-offline client's `sync_token` aged out of the retention window,
   discard the expired token, perform a full state resync, and resume from the
   new `next_sync_token`.
"""

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
        exclude_actors: list[str] | None = None,
        limit: int = 200,
    ) -> EventFeedListVO:
        """Poll a user's incremental domain event feed (`GET /api/extended/events`).

        When called with `sync_token=None`, returns retained events starting
        from the oldest entry in the retention window in chronological order
        (optionally narrowed by `event_types`, `file_id`, or `exclude_actors`).
        Callers can page forward while `has_more` is `True` using each response's
        `next_sync_token` until caught up to the most recent events, then reuse
        that `next_sync_token` on subsequent polls to fetch only newly recorded
        events.

        Args:
            sync_token: Opaque `next_sync_token` from a previous response, or
                `None` to read from the beginning of retained event history.
            event_types: Optional list of event type filters. Accepts exact
                `DomainEventType` values (defined in `supernote.models.events`,
                e.g. `DomainEventType.NOTE_PAGE_TRANSCRIBED`) or namespace prefix
                globs (`'vfs.*'`, `'note.*'`, `'schedule.*'`, `'summary.*'`).
            file_id: Optional VFS file ID to scope events to a single file/notebook.
            exclude_actors: Optional list of actor identifiers to exclude from
                results. Pass `['self']` to suppress events authored by the
                currently authenticated credential (API key, OAuth client, device,
                or web session).
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
            exclude_actors=",".join(exclude_actors) if exclude_actors else None,
            limit=limit,
        )
        params = {k: str(v) for k, v in dto.to_dict().items()}
        return await self._client.get_json(
            "/api/extended/events", EventFeedListVO, params=params
        )
