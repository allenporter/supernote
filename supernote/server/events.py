"""In-process asynchronous event bus (`LocalEventBus`) and domain event dataclasses.

Decouples mutating domain services (`supernote.server.services.file.FileService`,
`supernote.server.services.summary.SummaryService`, `supernote.server.services.schedule.ScheduleService`,
`supernote.server.services.processor.ProcessorService`) from downstream subscribers:
- `supernote.server.services.processor.ProcessorService` listens for `NoteUpdatedEvent`, `NoteDeletedEvent`, `SyncCompletedEvent`, and `BlobCleanupEvent`.
- `supernote.server.services.webhook.WebhookService` listens for `NoteUpdatedEvent` and `NoteProcessingCompletedEvent`.
- `supernote.server.socket` listens for VFS, summary, and schedule events to broadcast real-time Socket.IO messages to connected tablets and Web UI clients.

See `supernote.guides.architecture`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from supernote.models.summary import SummaryItem, SummaryTagItem

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base class for all events."""


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
class NoteProcessingCompletedEvent(Event):
    """Triggered when the asynchronous processing pipeline for a .note file completes."""

    file_id: int
    user_id: int
    file_path: str


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
class SummaryUpsertedEvent(Event):
    """Triggered when a summary group or leaf summary item is created or updated."""

    user_id: int
    summary: SummaryItem
    is_new: bool
    equipment_no: str | None = None


@dataclass
class SummaryDeletedEvent(Event):
    """Triggered when a summary group or leaf summary item is soft-deleted."""

    user_id: int
    summary_id: int
    is_summary_group: bool = False
    equipment_no: str | None = None


@dataclass
class VfsItemCreatedEvent(Event):
    """Triggered when a VFS file or directory is created, uploaded, or restored from recycle."""

    user_id: int
    item_id: int
    parent_id: int
    name: str
    is_folder: bool
    full_path: str
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None


@dataclass
class VfsItemMovedEvent(Event):
    """Triggered when a VFS file or directory is renamed in-place or moved to a new directory."""

    user_id: int
    item_id: int
    original_parent_id: int
    new_parent_id: int
    original_name: str
    new_name: str
    original_full_path: str
    new_full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None


@dataclass
class VfsItemCopiedEvent(Event):
    """Triggered when a VFS file or directory is copied."""

    user_id: int
    source_id: int
    new_id: int
    source_parent_id: int
    new_parent_id: int
    original_name: str
    new_name: str
    original_full_path: str
    new_full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None


@dataclass
class VfsItemDeletedEvent(Event):
    """Triggered when a VFS file or directory is soft-deleted into the recycle bin."""

    user_id: int
    item_id: int
    parent_id: int
    name: str
    full_path: str
    is_folder: bool
    size: int = 0
    md5: str | None = None
    equipment_no: str | None = None


@dataclass
class BlobCleanupEvent(Event):
    """Requests asynchronous removal of candidate storage keys in USER_DATA_BUCKET if no file or summary rows reference them."""

    storage_keys: set[str]


EventHandler = Callable[[Any], Awaitable[Any]]


class LocalEventBus:
    """A simple in-process event bus using asyncio."""

    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[EventHandler]] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    def subscribe[E: Event](
        self, event_type: type[E], handler: Callable[[E], Awaitable[Any]]
    ) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {handler} to {event_type.__name__}")

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        event_type = type(event)
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
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
