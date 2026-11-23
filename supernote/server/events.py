"""In-process asynchronous event bus (`LocalEventBus`) and domain event dataclasses.

Decouples mutating domain services (`supernote.server.services.file.FileService`,
`supernote.server.services.summary.SummaryService`, `supernote.server.services.schedule.ScheduleService`,
`supernote.server.services.processor.ProcessorService`) from downstream subscribers:
- `supernote.server.services.processor.ProcessorService` listens for `NoteUpdatedEvent`, `NoteDeletedEvent`, `SyncCompletedEvent`, and `BlobCleanupEvent`.
- `supernote.server.components.webhooks.service.WebhookService` listens for `NoteUpdatedEvent` and `NoteProcessingCompletedEvent`.
- `supernote.server.components.socketio` listens for VFS, summary, and schedule events to broadcast real-time Socket.IO messages to connected tablets and Web UI clients.

See `supernote.guides.architecture`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from mashumaro import field_options
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.events import DomainEntityType, DomainEventType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.models.summary import SummaryItem, SummaryTagItem

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base class for all events."""


@dataclass
class DomainEvent(Event, DataClassJSONMixin):
    """Base class for domain events recorded in `f_user_event` and dumped directly to the wire."""

    EVENT_TYPE: ClassVar[DomainEventType]
    ENTITY_TYPE: ClassVar[DomainEntityType]
    DEFAULT_ACTOR: ClassVar[str] = "user:web"

    user_id: int

    @property
    def entity_id(self) -> str:
        """Stable identifier of the affected entity."""
        raise NotImplementedError

    @property
    def related_file_id(self) -> int | None:
        """Associated VFS file ID when applicable."""
        return None

    @property
    def actor(self) -> str:
        """Originating actor identifier (e.g. 'user:web', 'device:<id>', 'system:processor')."""
        equipment_no = getattr(self, "equipment_no", None)
        return f"device:{equipment_no}" if equipment_no else self.DEFAULT_ACTOR

    def to_payload(self) -> dict[str, Any]:
        """Serialize event fields into the wire `payload` dict, omitting envelope metadata."""
        data = self.to_dict()
        data.pop("user_id", None)
        data.pop("equipment_no", None)
        return data


@dataclass
class NoteUpdatedEvent(Event):
    """Triggered when a .note file is created or updated."""

    file_id: int
    user_id: int
    file_path: str
    defer_processing: bool = False


@dataclass
class NoteDeletedEvent(Event):
    """Triggered when a .note file is deleted."""

    file_id: int
    user_id: int


@dataclass
class NoteProcessingCompletedEvent(DomainEvent):
    """Triggered when the asynchronous processing pipeline for a .note file completes."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.NOTE_PROCESSING_COMPLETED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE
    DEFAULT_ACTOR: ClassVar[str] = "system:processor"

    file_id: int = field(metadata=field_options(serialize=str))
    file_path: str

    @property
    def entity_id(self) -> str:
        return str(self.file_id)

    @property
    def related_file_id(self) -> int | None:
        return self.file_id


@dataclass
class NoteProcessingFailedEvent(NoteProcessingCompletedEvent):
    """Triggered when a processing module fails for a .note file or page."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.NOTE_PROCESSING_FAILED

    module_name: str = ""
    error: str = ""
    page_id: str | None = None


@dataclass
class NotePagesDeltaEvent(NoteProcessingCompletedEvent):
    """Triggered when structural page changes (add/modify/move/delete) are detected in a .note file."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.NOTE_PAGES_DELTA

    added_pages: list[str] = field(default_factory=list)
    modified_pages: list[str] = field(default_factory=list)
    moved_pages: list[str] = field(default_factory=list)
    deleted_pages: list[str] = field(default_factory=list)


@dataclass
class NotePageTranscribedEvent(NoteProcessingCompletedEvent):
    """Triggered when OCR finishes updating a single notebook page's text transcript."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.NOTE_PAGE_TRANSCRIBED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.NOTE_PAGE

    page_id: str = ""
    page_index: int = 0
    text_content: str = ""

    @property
    def entity_id(self) -> str:
        return f"{self.file_id}:{self.page_id}"


@dataclass
class SyncCompletedEvent(Event):
    """Triggered when a device file synchronization session completes."""

    user_id: int
    equipment_no: str | None = None


@dataclass
class ScheduleUpdatedEvent(Event):
    """Triggered when a schedule task group or task is created, updated, or deleted."""

    user_id: int
    task_list_id: str | None = None
    task_id: str | None = None
    equipment_no: str | None = None


def _link_file_id(links: str | None) -> int | None:
    """Extract numeric `file_id` from a Base64-encoded `ScheduleTaskLinkDTO` when present."""
    if not links:
        return None
    try:
        dto = ScheduleTaskLinkDTO.from_b64(links)
    except Exception:
        return None
    if dto.file_id and dto.file_id.strip().isdigit():
        return int(dto.file_id.strip())
    return None


@dataclass
class ScheduleTaskCreatedEvent(DomainEvent):
    """Triggered when a schedule task is created."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SCHEDULE_TASK_CREATED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.SCHEDULE_TASK

    task_id: str
    task_list_id: str | None = None
    title: str = ""
    detail: str | None = None
    status: str = "needsAction"
    due_time: int | None = None
    links: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return self.task_id

    @property
    def related_file_id(self) -> int | None:
        return _link_file_id(self.links)


@dataclass
class ScheduleTaskUpdatedEvent(ScheduleTaskCreatedEvent):
    """Triggered when semantic fields on a schedule task are updated."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SCHEDULE_TASK_UPDATED


@dataclass
class ScheduleTaskDeletedEvent(DomainEvent):
    """Triggered when a schedule task is deleted."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SCHEDULE_TASK_DELETED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.SCHEDULE_TASK

    task_id: str
    task_list_id: str | None = None
    title: str = ""
    status: str = "needsAction"
    links: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return self.task_id

    @property
    def related_file_id(self) -> int | None:
        return _link_file_id(self.links)


@dataclass
class SummaryTagUpsertedEvent(Event):
    """Triggered when a summary tag is created or updated."""

    user_id: int
    tag: SummaryTagItem
    is_new: bool
    equipment_no: str | None = None


@dataclass
class SummaryTagDeletedEvent(Event):
    """Triggered when a summary tag is deleted."""

    user_id: int
    tag_id: int
    equipment_no: str | None = None


@dataclass
class SummaryUpsertedEvent(DomainEvent):
    """Triggered when a summary group or leaf summary item is created or updated."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SUMMARY_UPSERTED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.SUMMARY

    summary: SummaryItem
    is_new: bool
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.summary.id or self.summary.unique_identifier or "unknown")

    @property
    def related_file_id(self) -> int | None:
        return self.summary.file_id


@dataclass
class SummaryDeletedEvent(DomainEvent):
    """Triggered when a summary group or leaf summary item is deleted."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SUMMARY_DELETED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.SUMMARY

    summary_id: int = field(metadata=field_options(serialize=str))
    is_summary_group: bool = False
    file_id: int | None = field(default=None, metadata=field_options(serialize=str))
    unique_identifier: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.summary_id)

    @property
    def related_file_id(self) -> int | None:
        return self.file_id


@dataclass
class VfsItemCreatedEvent(DomainEvent):
    """Triggered when a VFS file or directory is created, uploaded, or restored from recycle."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.VFS_CREATED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE

    item_id: int = field(metadata=field_options(serialize=str))
    parent_id: int = field(metadata=field_options(serialize=str))
    name: str
    is_folder: bool
    full_path: str
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.item_id)

    @property
    def related_file_id(self) -> int | None:
        return None if self.is_folder else self.item_id


@dataclass
class VfsContentUpdatedEvent(DomainEvent):
    """Triggered when an existing VFS file is overwritten with new content."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.VFS_CONTENT_UPDATED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE

    item_id: int = field(metadata=field_options(serialize=str))
    parent_id: int = field(metadata=field_options(serialize=str))
    name: str
    full_path: str
    size: int = 0
    old_md5: str | None = None
    new_md5: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.item_id)

    @property
    def related_file_id(self) -> int | None:
        return self.item_id


@dataclass
class VfsItemMovedEvent(DomainEvent):
    """Triggered when a VFS file or directory is renamed in-place or moved to a new directory."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.VFS_MOVED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE

    item_id: int = field(metadata=field_options(serialize=str))
    original_parent_id: int = field(metadata=field_options(serialize=str))
    new_parent_id: int = field(metadata=field_options(serialize=str))
    original_name: str
    new_name: str
    original_full_path: str
    new_full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.item_id)

    @property
    def related_file_id(self) -> int | None:
        return None if self.is_folder else self.item_id


@dataclass
class VfsItemCopiedEvent(DomainEvent):
    """Triggered when a VFS file or directory is copied."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.VFS_COPIED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE

    source_id: int = field(metadata=field_options(serialize=str))
    new_id: int = field(metadata=field_options(serialize=str))
    source_parent_id: int = field(metadata=field_options(serialize=str))
    new_parent_id: int = field(metadata=field_options(serialize=str))
    original_name: str
    new_name: str
    original_full_path: str
    new_full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.new_id)

    @property
    def related_file_id(self) -> int | None:
        return None if self.is_folder else self.new_id


@dataclass
class VfsItemDeletedEvent(DomainEvent):
    """Triggered when a VFS file or directory is soft-deleted into the recycle bin."""

    EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.VFS_DELETED
    ENTITY_TYPE: ClassVar[DomainEntityType] = DomainEntityType.FILE

    item_id: int = field(metadata=field_options(serialize=str))
    parent_id: int = field(metadata=field_options(serialize=str))
    name: str
    full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None

    @property
    def entity_id(self) -> str:
        return str(self.item_id)

    @property
    def related_file_id(self) -> int | None:
        return None if self.is_folder else self.item_id


@dataclass
class BlobCleanupEvent(Event):
    """Requests asynchronous removal of candidate storage keys in USER_DATA_BUCKET if no file or summary rows reference them."""

    storage_keys: set[str]


@dataclass
class DomainEventRecorded(Event):
    """Published after a durable `UserEventDO` row is committed to `f_user_event`."""

    user_id: int
    seq: int
    timestamp_ms: int
    event_type: str
    actor: str
    entity_type: str
    entity_id: str
    related_file_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


EventHandler = Callable[[Any], Awaitable[Any]]


class LocalEventBus:
    """A simple in-process event bus using asyncio."""

    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[tuple[EventHandler, bool]]] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    def subscribe[E: Event](
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[Any]],
        *,
        inline: bool = False,
    ) -> None:
        """Subscribe a handler to an event type.

        When `inline=True`, `publish()` awaits the handler directly in subscription
        order before returning.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((handler, inline))
        logger.debug(f"Subscribed {handler} to {event_type.__name__} (inline={inline})")

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        event_type = type(event)
        if event_type in self._subscribers:
            for handler, inline in self._subscribers[event_type]:
                if inline:
                    await self._safe_execute(handler, event)
                else:
                    # We fire and forget using create_task to ensure background execution
                    # and not block the caller (e.g., the API response).
                    task = asyncio.create_task(self._safe_execute(handler, event))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

    async def _safe_execute(self, handler: EventHandler, event: Event) -> None:
        """Execute handler and log exceptions."""
        try:
            await handler(event)
        except Exception:
            logger.exception(f"Error handling event {event} with handler {handler}")
