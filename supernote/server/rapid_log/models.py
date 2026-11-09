"""Declarative state, input snapshot, and planned action models for Rapid Logging reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from supernote.server.utils.rapid_log import (
    RapidLogItem,
    RapidLogKind,
    RapidLogTaskState,
)

__all__ = [
    "CreateTaskAction",
    "DeleteTaskAction",
    "EntryLinkState",
    "MAX_TASK_DETAIL_LENGTH",
    "MAX_TASK_TITLE_LENGTH",
    "NOTE_APP_NAME",
    "NotebookPageInput",
    "ReconciliationPlan",
    "RemoteTaskSnapshot",
    "SyncedRapidLogEntry",
    "TaskImportance",
    "TaskStatus",
    "UpdateTaskAction",
]

MAX_TASK_TITLE_LENGTH = 255
MAX_TASK_DETAIL_LENGTH = 1 * 1024 * 1024  # 1 MiB
NOTE_APP_NAME = "Note"


class TaskStatus(StrEnum):
    """Canonical `ScheduleTask` completion status values."""

    NEEDS_ACTION = "needsAction"
    COMPLETED = "completed"


class TaskImportance(StrEnum):
    """Canonical `ScheduleTask` priority values emitted by Rapid Logging."""

    NORMAL = "normal"
    HIGH = "high"


class EntryLinkState(StrEnum):
    """Lifecycle ownership state between a notebook Rapid Log entry and a digital To-Do task."""

    UNLINKED = "UNLINKED"
    """Never owned a To-Do task (e.g. EVENT, NOTE, pre-completed historical X, or initial strikethrough)."""

    ACTIVE = "ACTIVE"
    """Currently owns `schedule_task_id`."""

    MIGRATED = "MIGRATED"
    """Previously owned a To-Do task that was handed off to a newer page or notebook."""

    CANCELLED_INK = "CANCELLED_INK"
    """Previously open To-Do task was cancelled via handwritten strikethrough (`~~...~~`)."""

    DISMISSED_DIGITAL = "DISMISSED_DIGITAL"
    """Previously linked To-Do task was manually deleted in the To-Do app; prevents zombie resurrection."""


@dataclass(frozen=True, slots=True)
class NotebookPageInput:
    """Pure representation of a single notebook page at reconciliation time."""

    page_id: str
    page_index: int
    text_content: str | None = None
    page_modified_ms: int = 0
    page_date_ms: int | None = None
    page_created_ms: int | None = None
    items: tuple[RapidLogItem, ...] | None = None


@dataclass(frozen=True, slots=True)
class RemoteTaskSnapshot:
    """Read-only snapshot of an existing digital `ScheduleTask`."""

    task_id: str
    title: str
    detail: str | None = None
    status: str = TaskStatus.NEEDS_ACTION
    importance: str | None = None
    due_time: int | None = None
    completed_time: int | None = None
    links: str | None = None
    task_list_id: str | None = None
    update_time: int = 0


@dataclass(frozen=True, slots=True)
class SyncedRapidLogEntry:
    """Persisted reconciliation baseline for a single extracted Rapid Logging entry."""

    file_id: int
    file_path: str
    page_id: str
    page_index: int
    item_order: int
    occurrence_index: int
    kind: RapidLogKind
    normalized_text: str
    text: str
    detail: str | None = None
    task_state: RapidLogTaskState | None = None
    is_starred: bool = False
    is_cancelled: bool = False
    page_date_ms: int | None = None
    page_created_ms: int | None = None
    link_state: EntryLinkState = EntryLinkState.UNLINKED
    schedule_task_id: str | None = None
    last_synced_ms: int = 0
    entry_id: int | str | None = None


@dataclass(frozen=True, slots=True)
class CreateTaskAction:
    """Instruction to create a new `ScheduleTask`."""

    task_id: str
    title: str
    detail: str
    status: str
    importance: str
    due_time: int | None
    completed_time_ms: int | None
    links: str
    last_modified_ms: int
    order_hint: int


@dataclass(frozen=True, slots=True)
class UpdateTaskAction:
    """Instruction to update specific fields on an existing `ScheduleTask`."""

    task_id: str
    updates: Mapping[str, Any]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.updates, MappingProxyType):
            object.__setattr__(self, "updates", MappingProxyType(dict(self.updates)))


@dataclass(frozen=True, slots=True)
class DeleteTaskAction:
    """Instruction to delete an existing `ScheduleTask`."""

    task_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    """Complete deterministic output of `reconcile_rapid_log`."""

    entries: list[SyncedRapidLogEntry]
    updated_external_entries: list[SyncedRapidLogEntry] = field(default_factory=list)
    create_tasks: list[CreateTaskAction] = field(default_factory=list)
    update_tasks: list[UpdateTaskAction] = field(default_factory=list)
    delete_tasks: list[DeleteTaskAction] = field(default_factory=list)

    @property
    def has_task_mutations(self) -> bool:
        """Return True if any To-Do task creation, update, or deletion is planned."""
        return bool(self.create_tasks or self.update_tasks or self.delete_tasks)
