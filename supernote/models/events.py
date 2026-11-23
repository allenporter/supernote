"""Data models for the per-user domain event feed.

These models define the event types, entity categories, request parameters, and
wire envelopes shared by `GET /api/extended/events`, `EventsClient`, and MCP
event tools/notifications.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse


class DomainEventType(StrEnum):
    """Canonical domain event type identifiers recorded in `f_user_event`.

    Each event carries a domain-specific `payload` dictionary on `DomainEventVO`
    describing the mutation delta so incremental consumers can react without
    re-fetching unchanged resources.
    """

    VFS_CREATED = "vfs.created"
    """File or folder created in the VFS (`entity_type='file'`, serialized from `VfsItemCreatedEvent`)."""

    VFS_CONTENT_UPDATED = "vfs.content_updated"
    """Existing VFS file overwritten with new content (`entity_type='file'`, serialized from `VfsContentUpdatedEvent`)."""

    VFS_MOVED = "vfs.moved"
    """File or folder renamed or moved (`entity_type='file'`, serialized from `VfsItemMovedEvent`)."""

    VFS_COPIED = "vfs.copied"
    """File or folder copied (`entity_type='file'`, serialized from `VfsItemCopiedEvent`)."""

    VFS_DELETED = "vfs.deleted"
    """File or folder deleted from the VFS (`entity_type='file'`, serialized from `VfsItemDeletedEvent`)."""

    NOTE_PAGES_DELTA = "note.pages_delta"
    """Structural page changes detected in a `.note` file (`entity_type='file'`, serialized from `NotePagesDeltaEvent`)."""

    NOTE_PAGE_TRANSCRIBED = "note.page_transcribed"
    """Single notebook page OCR text updated (`entity_type='note_page'`, serialized from `NotePageTranscribedEvent`)."""

    NOTE_PROCESSING_COMPLETED = "note.processing_completed"
    """Background processing pipeline finished for a `.note` file (`entity_type='file'`, serialized from `NoteProcessingCompletedEvent`)."""

    NOTE_PROCESSING_FAILED = "note.processing_failed"
    """Background processing pipeline failed for a `.note` file (`entity_type='file'`, serialized from `NoteProcessingFailedEvent`)."""

    SCHEDULE_TASK_CREATED = "schedule.task_created"
    """Schedule to-do task created (`entity_type='schedule_task'`, serialized from `ScheduleTaskCreatedEvent`)."""

    SCHEDULE_TASK_UPDATED = "schedule.task_updated"
    """Schedule to-do task updated (`entity_type='schedule_task'`, serialized from `ScheduleTaskUpdatedEvent`)."""

    SCHEDULE_TASK_DELETED = "schedule.task_deleted"
    """Schedule to-do task deleted (`entity_type='schedule_task'`, serialized from `ScheduleTaskDeletedEvent`)."""

    SUMMARY_UPSERTED = "summary.upserted"
    """Summary or synthesis item created or updated (`entity_type='summary'`, serialized from `SummaryUpsertedEvent`)."""

    SUMMARY_DELETED = "summary.deleted"
    """Summary or synthesis item deleted (`entity_type='summary'`, serialized from `SummaryDeletedEvent`)."""


class DomainEntityType(StrEnum):
    """Canonical target entity categories for domain events."""

    FILE = "file"
    NOTE_PAGE = "note_page"
    SCHEDULE_TASK = "schedule_task"
    SUMMARY = "summary"


@dataclass
class EventFeedRequestDTO(DataClassJSONMixin):
    """Query parameters DTO for polling the per-user domain event feed.

    Used by: GET /api/extended/events
    """

    sync_token: str | None = field(
        metadata=field_options(alias="syncToken"), default=None
    )
    """Opaque checkpoint token returned as `nextSyncToken` by a prior call (`None` to start from the beginning)."""

    event_types: str | None = field(
        metadata=field_options(alias="eventTypes"), default=None
    )
    """Optional comma-separated `DomainEventType` values or namespace globs (`'vfs.*'`, `'note.*'`, `'schedule.*'`, `'summary.*'`)."""

    file_id: int | None = field(
        metadata=field_options(alias="fileId", serialize=str), default=None
    )
    """Optional VFS file ID filter."""

    exclude_actors: str | None = field(
        metadata=field_options(alias="excludeActors"), default=None
    )
    """Optional comma-separated actor identifiers to omit from results (e.g. `'self'` or `'api_key:<id>'`)."""

    limit: int = 200
    """Maximum number of events to return (`1..1000`, default `200`)."""

    @property
    def event_type_list(self) -> list[str] | None:
        """Return parsed event type filter strings, or `None` when unset."""
        if not self.event_types:
            return None
        return [
            part.strip() for part in self.event_types.split(",") if part.strip()
        ] or None

    @property
    def exclude_actor_list(self) -> list[str] | None:
        """Return parsed excluded actor strings, or `None` when unset."""
        if not self.exclude_actors:
            return None
        return [
            part.strip() for part in self.exclude_actors.split(",") if part.strip()
        ] or None

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


@dataclass
class DomainEventVO(DataClassJSONMixin):
    """VO for a single domain event in the per-user event feed.

    Used by: GET /api/extended/events
    """

    seq: str
    """Strictly monotonic 64-bit sequence ID of this event, serialized as a string."""

    timestamp: int
    """Event recording timestamp in UTC epoch milliseconds."""

    event_type: str = field(metadata=field_options(alias="eventType"))
    """Domain event type identifier (see `DomainEventType` in `supernote.models.events`)."""

    actor: str
    """Originating mutation source (`'user:web'`, `'device:<equipment_no>'`, `'api_key:<id>'`, `'oauth:<client_id>'`, or `'system:processor'`)."""

    entity_type: str = field(metadata=field_options(alias="entityType"))
    """Target entity category (see `DomainEntityType` in `supernote.models.events`)."""

    entity_id: str = field(metadata=field_options(alias="entityId"))
    """Stable identifier of the affected entity (e.g. file ID, '<file_id>:<page_index>', task ID)."""

    related_file_id: int | None = field(
        metadata=field_options(alias="relatedFileId", serialize=str), default=None
    )
    """Associated VFS file ID when applicable (serialized as a string on the wire)."""

    payload: dict[str, Any] = field(default_factory=dict)
    """Event-specific delta metadata (paths, hashes, changed fields, OCR text diffs, etc.)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class EventFeedListVO(BaseResponse):
    """Response VO for querying the per-user domain event feed.

    Used by: GET /api/extended/events
    """

    events: list[DomainEventVO] = field(default_factory=list)
    """Ordered list of domain events occurring after the requested `syncToken`."""

    next_sync_token: str | None = field(
        metadata=field_options(alias="nextSyncToken"), default=None
    )
    """Opaque checkpoint token to pass as `syncToken` on the next request (`None` if no events exist yet)."""

    has_more: bool = field(metadata=field_options(alias="hasMore"), default=False)
    """Whether additional matching events remain beyond the page `limit`."""

    class Config(BaseConfig):
        serialize_by_alias = True
